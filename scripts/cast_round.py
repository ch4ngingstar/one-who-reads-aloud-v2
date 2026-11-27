"""Casting round: render real book lines through the production speech engines.

    python scripts/cast_round.py data/voice-design/round2/spec.json

One render pass feeds two listening tools:
  * shoot-out: blind OmniVoice-vs-Fish A/B per character (built with build_listening_pack.py), and
  * recast: a casting page per character being recast, where every voice option is rendered
    by every engine behind randomised "take A/B" labels; a private key decodes the picks.

Every take goes through the same providers a chapter render uses (exact reference transcripts,
Fish's reference trimming and delivery cues, studio PCM), and gets the same read-back retake,
so what is heard is what the pipeline will produce. Renders are cached: an interrupted run
(power cut) resumes where it stopped.
"""

import argparse
import base64
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_listening_pack import listening_wav  # noqa: E402
from casting import choose_voice  # noqa: E402
from speech_audio import check_utterance, studio_pcm  # noqa: E402
from speech_providers import provider_for  # noqa: E402
from spoken_text import spoken_reading  # noqa: E402
from state_manager import _resolve_stored_path  # noqa: E402
from take_review import TakeReviewer  # noqa: E402

DB = ROOT / "src/data/pipeline.db"
DESIGN_ROOT = (ROOT / "data/voice-design").resolve()
QUOTES = "\"'“”‘’ "


def slug(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


@dataclass(frozen=True)
class Take:
    """Everything a provider reads from a cue, plus where the take is stored."""
    line_id: int
    index: int
    actor: str
    emotion: str
    reference: str
    reference_hash: str
    text: str
    out: Path


def resolve_line(con, character, ref):
    if "id" in ref:
        row = con.execute("select speaker, text, emotion from lines where id = ?", (ref["id"],)).fetchone()
        if row is None:
            raise SystemExit(f"{character}: no line with id {ref['id']}")
        if row[0] != character:
            raise SystemExit(f"{character}: line {ref['id']} is labelled {row[0]}")
        return row[1].strip(QUOTES), ref.get("emotion", row[2])
    text = ref["text"].strip(QUOTES)
    if "emotion" in ref:
        return text, ref["emotion"]
    row = con.execute("select emotion from lines where speaker = ? and trim(text, ?) = ? limit 1",
                      (character, QUOTES, text)).fetchone()
    return text, row[0] if row else "neutral"


def reference_for(voice, character, voices):
    path = voice["path"]
    if path == "registered":
        choice = choose_voice(character, "neutral", voices)
        if choice.fallback:
            raise SystemExit(f"{character} has no registered voice")
        path = choice.path
    resolved = _resolve_stored_path(path)
    resolved = resolved if resolved.is_absolute() else ROOT / path
    if not resolved.is_file():
        raise SystemExit(f"Missing reference {resolved}")
    resolved = resolved.resolve()
    # Designed candidates carry their exact script in a JSON sidecar; expose it the way
    # registered designed voices do, so neither engine has to guess the words.
    meta, sidecar = resolved.with_suffix(".json"), resolved.with_suffix(".txt")
    if meta.is_file() and not sidecar.is_file() and DESIGN_ROOT in resolved.parents:
        sidecar.write_text(json.loads(meta.read_text(encoding="utf-8"))["reference_script"] + "\n",
                           encoding="utf-8")
    return resolved


def make_take(character, emotion, reference, text, out, pronunciations):
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    key = int(hashlib.sha256(str(out).encode()).hexdigest()[:8], 16)
    return Take(key, key, character, emotion, str(reference), digest,
                spoken_reading(text, None, pronunciations), out)


def record(provider, reviewer, takes):
    """Render missing takes with the chapter renderer's read-back retake rule."""
    missing = [t for t in takes if not t.out.is_file()]
    for start in range(0, len(missing), provider.batch_size):
        group = missing[start:start + provider.batch_size]
        for take, audio in zip(group, provider.render([(t, t.text) for t in group])):
            audio = studio_pcm(audio)
            check_utterance(audio, take.text)
            audit = reviewer.check(audio, take.text)
            if audit["review"]:
                alt = studio_pcm(provider.render([(take, take.text)])[0])
                second = reviewer.check(alt, take.text)
                if (not second["review"], second["score"]) > (False, audit["score"]):
                    audio = alt
            take.out.parent.mkdir(parents=True, exist_ok=True)
            staging = take.out.with_suffix(".part")
            staging.write_bytes(audio)
            staging.replace(take.out)
            print(f"  {take.actor}: {take.out.name}", flush=True)


def mp3_src(path):
    data = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "wav", "-i", "-", "-c:a", "libmp3lame",
                           "-b:a", "96k", "-f", "mp3", "-"],
                          input=listening_wav(path), check=True, capture_output=True).stdout
    return "data:audio/mpeg;base64," + base64.b64encode(data).decode("ascii")


def recast_section(character, lines, options, note=""):
    rows = []
    for option in options:
        clips = "".join(f'<div class="clip"><span>{html.escape(label)}</span>'
                        f'<audio controls preload="metadata" src="{mp3_src(path)}"></audio></div>'
                        for path, label in option["clips"])
        rows.append(f'<div class="option"><label class="pick"><input type="radio" '
                    f'name="pick:{html.escape(character)}" value="{option["value"]}"> '
                    f'{html.escape(option["title"])}</label><div class="clips">{clips}</div></div>')
    listed = "".join(f"<li>{html.escape(t)}</li>" for t in lines)
    section = f"""<section data-character="{html.escape(character)}">
  <h2>{html.escape(character)}</h2>
  <p class="brief">Each voice is played by two different speech engines, as take A and take B
  (which engine is which is hidden and shuffled per voice). Pick the single best take.</p>
  <details><summary>Book lines read in this audition</summary><ol>{listed}</ol></details>
  {''.join(rows)}
  <label class="pick none"><input type="radio" name="pick:{html.escape(character)}" value="none"> None of these</label>
  <label class="notes">Notes <textarea name="notes:{html.escape(character)}" rows="2"></textarea></label>
</section>"""
    return section.replace('<p class="brief">', f'<p class="brief">{html.escape(note)} ', 1) if note else section


def recast_page(sections, pack):
    template = (ROOT / "scripts/casting_page.html").read_text(encoding="utf-8")
    return template.replace("__PACK__", pack).replace("__SECTIONS__", chr(10).join(sections))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    out = args.spec.parent.resolve()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    voices = dict(con.execute("select speaker, ref_audio_path from voices"))
    pronunciations = dict(con.execute("select spelling, reading from pronunciations"))
    engines = {name: ROOT / path for name, path in spec["engines"].items()}
    jobs = {name: [] for name in engines}

    shootout = []
    for character, refs in spec.get("shootout", {}).items():
        reference = reference_for({"path": "registered"}, character, voices)
        for k, ref in enumerate(refs, 1):
            text, emotion = resolve_line(con, character, ref)
            variants = []
            for engine in engines:
                take = make_take(character, emotion, reference, text,
                                 out / "shootout" / f"{slug(character)}-{k}-{slug(engine)}.wav", pronunciations)
                jobs[engine].append(take)
                variants.append({"label": engine, "path": str(take.out)})
            shootout.append({"kind": "line", "roles": [character],
                             "title": f"{character}: “{text}”", "variants": variants})

    recasts = {}
    for character, plan in spec.get("recast", {}).items():
        lines = [resolve_line(con, character, ref) for ref in plan["lines"]]
        rng = random.Random(f"{spec['name']}:{character}")
        options, key = [], {}
        for voice_id, voice in plan["voices"].items():
            reference = reference_for(voice, character, voices)
            meta = reference.with_suffix(".json")
            described = json.loads(meta.read_text(encoding="utf-8")).get("instruct", "") if meta.is_file() else ""
            described = described.split(" Clean close-mic")[0]
            # A character can be auditioned on one engine only (the one its votes chose).
            order = list(plan.get("engines") or engines)
            rng.shuffle(order)
            for take_label, engine in zip("AB", order):
                takes = [make_take(character, emotion, reference, text,
                                   out / "recast" / slug(character) / f"{voice_id}-{slug(engine)}-line{k}.wav",
                                   pronunciations)
                         for k, (text, emotion) in enumerate(lines, 1)]
                jobs[engine].extend(takes)
                value = f"{voice_id}:{take_label}"
                key[value] = {"voice": voice_id, "engine": engine, "reference": str(reference)}
                title = f"{voice['title']} · take {take_label}" + (f" — {described}" if described else "")
                options.append({"value": value, "title": title,
                                "clips": [(reference, "voice sample")] +
                                         [(t.out, f"line {k}") for k, t in enumerate(takes, 1)]})
        recasts[character] = ([t for t, _ in lines], options, key, plan.get("note", ""))

    reviewer = TakeReviewer()
    for engine, takes in jobs.items():
        if all(t.out.is_file() for t in takes):
            continue
        print(f"{engine}: {sum(not t.out.is_file() for t in takes)} takes to render", flush=True)
        provider = provider_for(None, engines[engine], out / ".cache")
        with provider:
            record(provider, reviewer, takes)

    if shootout:
        manifest = out / "shootout" / "manifest.json"
        manifest.write_text(json.dumps({"comparisons": shootout}, indent=1, ensure_ascii=False), encoding="utf-8")
        pack = ROOT / "data/benchmarks" / f"listening-engines-{spec['name']}"
        subprocess.run([sys.executable, str(ROOT / "scripts/build_listening_pack.py"), "--manifest", str(manifest),
                        "--output", str(pack), "--seed", f"engines-{spec['name']}"], check=True)
    if recasts:
        # One page and one private key for the whole round.
        keys = {character: key for character, (_, _, key, _) in recasts.items()}
        pack = hashlib.sha256(json.dumps({c: sorted(k) for c, k in keys.items()}, ensure_ascii=False)
                              .encode()).hexdigest()[:16]
        sections = [recast_section(character, lines, options, note)
                    for character, (lines, options, key, note) in recasts.items()]
        page = out / f"{spec['name']}-casting.html"
        page.write_text(recast_page(sections, pack), encoding="utf-8")
        (out / f"{spec['name']}-key.json").write_text(json.dumps({"pack": pack, "characters": keys}, indent=2),
                                                      encoding="utf-8")
        print(f"Casting page: {page} ({page.stat().st_size / 1e6:.1f} MB), {len(sections)} characters")


if __name__ == "__main__":
    main()
