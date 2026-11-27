"""Build an offline A/B audition from scene folders and optional manifest entries."""

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import random
import subprocess


CRITERIA = {
    "naturalness": "Naturalness",
    "identity": "Character identity",
    "fit": "Fit in context",
    "overall": "Overall preference",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stable_id(value):
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()[:24]


def prepare_variant(spec, base):
    path = (base / spec["path"]).resolve()
    with path.open("rb") as audio:
        if audio.read(4) not in (b"RIFF", b"RF64") or audio.read(8)[4:] != b"WAVE":
            raise ValueError(f"Expected WAV audio at {path}")
        audio.seek(0)
        digest = hashlib.file_digest(audio, "sha256").hexdigest()
    label = spec["label"]
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"A private variant label is required for {path}")
    return {**spec, "path": str(path), "sha256": digest}


def scene_spec(scene):
    report_path = scene / "report.json"
    report = read_json(report_path) if report_path.is_file() else []
    turns = report.get("lines", []) if isinstance(report, dict) else report
    roles = list(dict.fromkeys(
        turn["speaker"] for turn in turns
        if turn.get("speaker") and turn["speaker"].casefold() != "narrator"
    ))
    return {
        "kind": "scene",
        "roles": roles,
        "variants": [
            {"label": "current", "path": "current.wav"},
            {"label": "candidate", "path": "candidate.wav"},
        ],
        "report": report,
    }


def prepare_comparison(spec, base):
    kind = spec.get("kind", "scene")
    if kind not in ("scene", "line", "reference"):
        raise ValueError(f"Unknown comparison kind: {kind}")
    roles = spec.get("roles", [])
    if not isinstance(roles, list) or any(
        not isinstance(role, str) or not role.strip() for role in roles
    ):
        raise ValueError("roles must be a list of nonempty character names")
    title = spec.get("title", "")
    if not isinstance(title, str):
        raise ValueError("title must be a neutral listener-facing string")
    variants = [prepare_variant(variant, base) for variant in spec["variants"]]
    if len(variants) != 2 or variants[0]["label"] == variants[1]["label"]:
        raise ValueError("Each comparison requires two distinct private variant labels")
    return {**spec, "kind": kind, "roles": list(dict.fromkeys(roles)),
            "title": title, "variants": variants}


def randomize(comparisons, seed):
    rng = random.Random(seed)
    rng.shuffle(comparisons)
    next_swaps = {}
    for item in comparisons:
        variants = sorted(item["variants"], key=lambda variant: variant["label"])
        group = tuple(variant["label"] for variant in variants)
        if group not in next_swaps:
            next_swaps[group] = rng.choice([False, True])
        if next_swaps[group]:
            variants.reverse()
        next_swaps[group] = not next_swaps[group]
        item["sides"] = dict(zip("AB", variants))


def rating_row(scope, label, criteria):
    options = "".join(
        f'<option value="{value}">{caption}</option>'
        for value, caption in [("", "Choose"), ("A", "A"), ("B", "B"),
                               ("tie", "Tie"), ("neither", "Neither")]
    )
    cells = "".join(
        f'<td><select name="{scope}:{key}" aria-label="{html.escape(label)} — {CRITERIA[key]}">'
        f'{options}</select></td>' for key in criteria
    )
    return f'<tr><th scope="row">{html.escape(label)}</th>{cells}</tr>'


LOUDNESS_TARGET = -20.0  # the level cast_mix gives every actor in a finished chapter


def listening_wav(path, target=LOUDNESS_TARGET):
    """WAV bytes for the listener, levelled to the chapter mix's loudness.

    Raw takes from different engines differ by up to ~7 LU, and the louder of two
    otherwise equal takes tends to win a blind vote. Finished chapters level every
    actor anyway, so a pack should compare delivery, not gain. A static gain keeps
    the clip's own dynamics; the peak stays under -1 dBFS.
    """
    import io

    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf

    audio, rate = sf.read(str(path), dtype="float64", always_2d=True)
    level = pyln.Meter(rate).integrated_loudness(audio) if len(audio) >= int(0.4 * rate) else float("-inf")
    if target is not None and np.isfinite(level):
        gain = 10 ** ((target - level) / 20)
        peak = float(np.max(np.abs(audio), initial=0.0))
        if peak:
            gain = min(gain, 10 ** (-1 / 20) / peak)
        audio = audio * gain
    out = io.BytesIO()
    sf.write(out, audio, rate, format="WAV", subtype="PCM_16")
    return out.getvalue()


def embedded_src(path, target=LOUDNESS_TARGET):
    # Embedding makes the page self-contained: file:// previews and copied pages
    # cannot resolve a sibling audio folder, which left every player silent.
    # MP3 keeps the page small enough for previewers; both sides of every pair
    # share the same codec, so the comparison stays fair.
    mp3 = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "wav", "-i", "-", "-c:a", "libmp3lame",
         "-b:a", "128k", "-f", "mp3", "-"],
        input=listening_wav(path, target), check=True, capture_output=True,
    ).stdout
    return "data:audio/mpeg;base64," + base64.b64encode(mp3).decode("ascii")


def comparison_html(item, number, pack_id, comparison_id, embed=True, target=LOUDNESS_TARGET):
    kind = item["kind"]
    headings = {"scene": "Scene", "line": "Line", "reference": "Voice sample"}
    title = html.escape(item["title"] or f"{headings[kind]} {number}")
    criteria = [key for key in CRITERIA if kind != "reference" or key != "fit"]
    headers = "".join(f'<th scope="col">{CRITERIA[key]}</th>' for key in criteria)
    scope_label = "Whole scene" if kind == "scene" else "Voice sample" if kind == "reference" else "Whole line"
    rows = rating_row("overall", scope_label, criteria)
    rows += "".join(
        rating_row(f"role:{index}", role, criteria)
        for index, role in enumerate(item["roles"])
        if kind == "scene" or len(item["roles"]) > 1
    )
    if kind in ("line", "reference") and len(item["roles"]) == 1:
        title += f' · {html.escape(item["roles"][0])}'
    def src(side):
        if embed:
            return embedded_src(item["sides"][side]["path"], target)
        return f"audio/{pack_id}/{comparison_id}-{side}.wav"

    audio = "".join(
        f'<div><strong>{side}</strong><audio aria-label="{side}" controls preload="metadata" '
        f'src="{src(side)}"></audio></div>'
        for side in "AB"
    )
    return f"""<fieldset data-id="{comparison_id}">
      <legend>{title}</legend>
      <div class="clips">{audio}</div>
      <div class="ratings"><table>
        <thead><tr><th scope="col">Rate</th>{headers}</tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
      <label class="notes">Notes <textarea name="notes" rows="2"></textarea></label>
    </fieldset>"""


def build_pack(comparisons, output, seed, embed=True, target=LOUDNESS_TARGET):
    if not comparisons:
        raise ValueError("Provide at least one scene folder or manifest comparison")
    randomize(comparisons, seed)
    # The public IDs encode the exact clip assignments and labels needed to decode votes.
    ids = [
        stable_id([number, item["kind"], item["title"], item["roles"], item["sides"]])
        for number, item in enumerate(comparisons, start=1)
    ]
    pack_id = stable_id({"version": 1, "comparisons": ids})
    audio = output / "audio" / pack_id
    audio.mkdir(parents=True, exist_ok=True)
    key = {"version": 1, "pack_id": pack_id, "comparisons": []}
    for number, (comparison_id, item) in enumerate(zip(ids, comparisons), start=1):
        for side, variant in item["sides"].items():
            (audio / f"{comparison_id}-{side}.wav").write_bytes(listening_wav(variant["path"], target))
        metadata = {name: value for name, value in item.items() if name not in ("variants", "sides")}
        key["comparisons"].append({
            **metadata, "number": number, "comparison_id": comparison_id, "sides": item["sides"],
        })
    template = Path(__file__).with_name("listening_pack.html").read_text(encoding="utf-8")
    rows = "".join(
        comparison_html(item, number, pack_id, comparison_id, embed, target)
        for number, (item, comparison_id) in enumerate(zip(comparisons, ids), start=1)
    )
    (output / "answer-key.json").write_text(json.dumps(key, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "index.html").write_text(
        template.replace("__PACK_ID__", pack_id).replace("__COMPARISONS__", rows),
        encoding="utf-8",
    )
    return output.resolve() / "index.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenes", type=Path, nargs="*", help="Directories with current.wav and candidate.wav")
    parser.add_argument("--manifest", type=Path, action="append", default=[],
                        help="JSON file with a comparisons array; audio paths are relative to the JSON file")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="dialogue-listening-v1", help="Change to reshuffle the pack")
    parser.add_argument("--external-audio", action="store_true",
                        help="Reference the audio folder instead of embedding clips (needs an HTTP server)")
    parser.add_argument("--no-loudness-match", action="store_true",
                        help="Play raw takes instead of levelling each to the chapter mix loudness")
    args = parser.parse_args()
    try:
        comparisons = [prepare_comparison(scene_spec(scene), scene) for scene in args.scenes]
        for manifest in args.manifest:
            comparisons.extend(
                prepare_comparison(spec, manifest.parent) for spec in read_json(manifest)["comparisons"]
            )
        print(build_pack(comparisons, args.output, args.seed, embed=not args.external_audio,
                         target=None if args.no_loudness_match else LOUDNESS_TARGET))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
