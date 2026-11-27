"""Clone designed voice candidates with OmniVoice (the narrator's engine) and build a casting page.

Run with the OmniVoice runtime after scripts/design_voices.py:
    models/omnivoice-runtime/.venv/Scripts/python.exe scripts/audition_designed_voices.py

For every character it renders two real lines of that character's dialogue from the book with
each designed candidate and with the currently registered voice, then writes
data/voice-design/casting.html: a self-contained page (audio embedded) for picking one voice
per character. Renders are cached on disk, so re-running only fills in what is missing.
"""

import argparse
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "src/data/pipeline.db"
BRIEFS = ROOT / "profiles/voice-briefs.json"
DESIGN = ROOT / "data/voice-design"
OMNI = ROOT / "models/omnivoice-runtime/checkpoints"
LINES_PER_CHARACTER = 2
# Speakers whose registered voice lives under another canonical name (see src/casting.py).
VOICE_ALIASES = {"Anvil": "Lord Valor"}
QUOTES = "\"'“”‘’ "


def slug(name):
    return name.lower().replace(" ", "_")


def book_lines(con, speaker, count):
    """Pick representative spoken lines: plain dialogue of a comfortable audition length."""
    rows = [text.strip(QUOTES) for (text,) in con.execute(
        "select text from lines where speaker = ? and kind = 'dialogue' order by chapter_id, line_index",
        (speaker,))]
    usable = [t for t in rows if 8 <= len(t.split()) <= 26 and not re.search(r"[\[\]<>{}]", t)]
    if len(usable) < count:
        raise SystemExit(f"Not enough usable dialogue for {speaker}")
    return random.Random(f"casting:{speaker}").sample(usable, count)


def registered_voice(con, speaker):
    name = VOICE_ALIASES.get(speaker, speaker)
    row = con.execute("select ref_audio_path from voices where speaker = ?", (name,)).fetchone()
    path = Path(row[0]) if row else None
    return path if path and path.is_file() else None


class Renderer:
    def __init__(self):
        import torch
        from omnivoice import OmniVoice

        if not torch.cuda.is_available():
            raise SystemExit("OmniVoice needs CUDA-enabled PyTorch")
        self.torch = torch
        self.model = OmniVoice.from_pretrained(str(OMNI), device_map="cuda:0", dtype=torch.float16)
        self.asr = None

    def transcript(self, path):
        cache = DESIGN / "_transcripts" / (hashlib.sha256(path.read_bytes()).hexdigest() + ".txt")
        if cache.is_file():
            return cache.read_text(encoding="utf-8")
        if self.asr is None:
            from faster_whisper import WhisperModel
            self.asr = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        segments, _ = self.asr.transcribe(str(path), language="en", beam_size=3,
                                          condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        if not text:
            raise ValueError(f"No speech detected in {path}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
        return text

    def render(self, reference, ref_text, lines, outputs):
        import soundfile as sf

        if all(out.is_file() for out in outputs):
            return False
        audio, sr = sf.read(str(reference), dtype="float32", always_2d=True)
        with self.torch.inference_mode():
            prompt = self.model.create_voice_clone_prompt(
                ref_audio=(self.torch.from_numpy(audio.mean(axis=1)).unsqueeze(0), sr), ref_text=ref_text)
            takes = self.model.generate(text=lines, language=["English"] * len(lines),
                                        voice_clone_prompt=[prompt] * len(lines), num_step=32)
        if len(takes) != len(lines):
            raise RuntimeError("OmniVoice returned a different number of takes than requested")
        for take, out in zip(takes, outputs):
            tmp = out.with_suffix(".tmp.wav")
            sf.write(str(tmp), take, 24000, subtype="PCM_16")
            os.replace(tmp, out)
        return True


def mp3_src(path):
    # Loudness-match every clip so the louder take never wins by volume alone.
    data = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-af",
                           "loudnorm=I=-18:TP=-1.5", "-ar", "24000", "-c:a", "libmp3lame", "-b:a", "96k",
                           "-f", "mp3", "-"], check=True, capture_output=True).stdout
    return "data:audio/mpeg;base64," + base64.b64encode(data).decode("ascii")


def player(path, label):
    return (f'<div class="clip"><span>{html.escape(label)}</span>'
            f'<audio controls preload="metadata" src="{mp3_src(path)}"></audio></div>')


def build_page(sections, pack):
    template = Path(__file__).with_name("casting_page.html").read_text(encoding="utf-8")
    body = []
    for s in sections:
        name = html.escape(s["name"])
        rows = []
        for option in s["options"]:
            clips = "".join(player(p, label) for p, label in option["clips"])
            rows.append(
                f'<div class="option"><label class="pick"><input type="radio" name="pick:{name}" '
                f'value="{option["value"]}"> {html.escape(option["title"])}</label>'
                f'<div class="clips">{clips}</div></div>')
        lines = "".join(f"<li>{html.escape(t)}</li>" for t in s["lines"])
        body.append(f"""<section data-character="{name}">
  <h2>{name}</h2>
  <p class="brief"><strong>Designed as:</strong> {html.escape(s['instruct'])}</p>
  <p class="evidence"><strong>The novel says:</strong> {html.escape(s['evidence'])}</p>
  <details><summary>Book lines read in this audition</summary><ol>{lines}</ol></details>
  {''.join(rows)}
  <label class="pick none"><input type="radio" name="pick:{name}" value="none"> None of these</label>
  <label class="notes">Notes <textarea name="notes:{name}" rows="2"></textarea></label>
</section>""")
    return template.replace("__PACK__", pack).replace("__SECTIONS__", "\n".join(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="Characters to audition (default: every brief)")
    parser.add_argument("--page-only", action="store_true", help="Rebuild the page from cached renders")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    briefs = json.loads(BRIEFS.read_text(encoding="utf-8"))["characters"]
    names = args.only or list(briefs)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    renderer = None if args.page_only else Renderer()
    started = time.monotonic()
    sections = []
    for name in names:
        folder = DESIGN / slug(name)
        candidates = sorted(folder.glob("cand_*.json"), key=lambda p: int(p.stem.split("_")[1]))
        if not candidates:
            print(f"{name}: no designed candidates yet, skipped", flush=True)
            continue
        # Hand-vetted lines win: saved speaker labels are noisy for minor characters.
        lines = briefs[name].get("audition_lines") or book_lines(con, name, LINES_PER_CHARACTER)
        options = []
        current = registered_voice(con, name)
        if current is not None:
            outs = [folder / f"current.line{k}.wav" for k in range(1, len(lines) + 1)]
            if renderer and renderer.render(current, renderer.transcript(current), lines, outs):
                print(f"{name}: current voice rendered", flush=True)
            if all(o.is_file() for o in outs):
                options.append({"value": "current", "title": f"Current voice ({current.name})",
                                "clips": [(current, "its reference clip")] +
                                         [(o, f"line {k}") for k, o in enumerate(outs, 1)]})
        for meta_path in candidates:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            wav = meta_path.with_suffix(".wav")
            n = meta["candidate"]
            outs = [folder / f"cand_{n}.line{k}.wav" for k in range(1, len(lines) + 1)]
            # The designed clip's words are known exactly, so no ASR guess is needed.
            if renderer and renderer.render(wav, meta["reference_script"], lines, outs):
                print(f"{name}: candidate {n} rendered", flush=True)
            if all(o.is_file() for o in outs):
                options.append({"value": f"cand_{n}", "title": f"New voice {n}",
                                "clips": [(wav, "designed voice")] +
                                         [(o, f"line {k}") for k, o in enumerate(outs, 1)]})
        sections.append({"name": name, "instruct": briefs[name]["instruct"],
                         "evidence": briefs[name]["novel_evidence"], "lines": lines, "options": options})
    pack = hashlib.sha256(json.dumps([(s["name"], [o["value"] for o in s["options"]]) for s in sections])
                          .encode()).hexdigest()[:16]
    page = DESIGN / "casting.html"
    page.write_text(build_page(sections, pack), encoding="utf-8")
    print(f"Casting page: {page} ({page.stat().st_size / 1e6:.1f} MB) in {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
