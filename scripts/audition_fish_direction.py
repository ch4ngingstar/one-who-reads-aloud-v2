"""Blind A/B: does each Fish S2 Pro emotion cue help, or over-act?

    python scripts/audition_fish_direction.py            # render pairs + write the manifest
    python scripts/build_listening_pack.py --manifest data/benchmarks/fish-direction/manifest.json \
        --output data/benchmarks/listening-fish-direction

For every non-neutral cue in profiles/fish-direction.json it picks real dialogue lines the
diarizer gave that emotion, spoken by registered principal characters, and renders each line
twice with the same seed: plain, and with the cue. Only the cue differs, so the owner's
preference per emotion decides which cues stay on. Renders are cached; re-runs fill gaps.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casting import choose_voice  # noqa: E402
from fish_provider import FishProvider, load_direction  # noqa: E402
from speech_audio import studio_pcm  # noqa: E402
from state_manager import _resolve_stored_path  # noqa: E402

DB = ROOT / "src/data/pipeline.db"
FISH = ROOT / "models/audio-cpp/Fish-Audio-S2-Pro-GGUF"
OUT = ROOT / "data/benchmarks/fish-direction"
PRINCIPALS = ["Sunny", "Nephis", "Cassie", "Kai", "Effie", "Rain", "Morgan", "Mordret", "Jet",
              "Seishan", "Anvil", "Jest", "Ki Song", "Asterion", "Aiko", "Tamar", "Ray"]
QUOTES = "\"'“”‘’ "


def pick_lines(con, emotion, voices, count):
    rows = con.execute(
        "select id, line_index, speaker, text from lines where kind='dialogue' and emotion=? "
        "and speaker in (%s) order by id" % ",".join("?" * len(PRINCIPALS)), (emotion, *PRINCIPALS)).fetchall()
    usable = [r for r in rows if 5 <= len(r[3].strip(QUOTES).split()) <= 28
              and not re.search(r"[\[\]<>{}]", r[3])
              and not choose_voice(r[2], emotion, voices).fallback]
    rng = random.Random(f"fish-direction:{emotion}")
    rng.shuffle(usable)
    chosen, speakers = [], set()
    for row in usable:  # prefer distinct speakers, so one voice doesn't decide an emotion
        if row[2] not in speakers:
            chosen.append(row)
            speakers.add(row[2])
        if len(chosen) == count:
            break
    return chosen


class Line:
    def __init__(self, row, emotion, voices):
        self.line_id, self.index, self.speaker, text = row
        self.text = text.strip(QUOTES)
        choice = choose_voice(self.speaker, emotion, voices)
        self.actor, self.emotion = choice.canonical, emotion
        self.reference = str(_resolve_stored_path(choice.path).resolve())
        self.reference_hash = hashlib.sha256(Path(self.reference).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-emotion", type=int, default=2)
    args = parser.parse_args()
    cues = {k: v for k, v in load_direction().items() if v}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    voices = dict(con.execute("select speaker, ref_audio_path from voices"))
    plan = []
    for emotion, tag in cues.items():
        rows = pick_lines(con, emotion, voices, args.per_emotion)
        if not rows:
            print(f"{emotion}: no usable labelled dialogue, skipped", flush=True)
        plan += [(emotion, tag, n, Line(row, emotion, voices)) for n, row in enumerate(rows, 1)]
    OUT.mkdir(parents=True, exist_ok=True)
    todo = [p for p in plan if not all((OUT / f"{p[0]}-{p[2]}-{v}.wav").is_file() for v in ("plain", "cued"))]
    if todo:
        provider = FishProvider(FISH, OUT, direction=cues)
        with provider:
            for emotion, tag, n, line in todo:
                for variant, direction in (("plain", {}), ("cued", cues)):
                    provider.direction = direction
                    provider.attempts.clear()  # same seed for both: only the cue differs
                    audio, = provider.render([(line, line.text)])
                    (OUT / f"{emotion}-{n}-{variant}.wav").write_bytes(studio_pcm(audio))
                print(f"{emotion} {n}: {line.speaker} rendered", flush=True)
    comparisons = [{
        "kind": "line", "roles": [line.speaker],
        "title": f"{line.speaker}, labelled '{emotion}': “{line.text}”",
        "variants": [{"label": f"{emotion}: plain", "path": f"{emotion}-{n}-plain.wav"},
                     {"label": f"{emotion}: cued {tag}", "path": f"{emotion}-{n}-cued.wav"}],
    } for emotion, tag, n, line in plan]
    (OUT / "manifest.json").write_text(json.dumps({"comparisons": comparisons}, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    print(f"{len(comparisons)} comparisons -> {OUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
