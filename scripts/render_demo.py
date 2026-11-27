"""Seed the original demo scene and record it with the directed cast, as the studio would.

    python scripts/render_demo.py                 # seed (or re-seed) and record
    python scripts/render_demo.py --cast profiles/omnivoice-all.json

The scene lives in scripts/seed_demo.py. Recording uses the same RecordingRoom and
AudioAssembler as the pipeline's Start button; the demo skips labelling because its
speakers are set by hand. Takes already recorded for unchanged lines are reused.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    parser.add_argument("--cast", default="profiles/full-cast.json",
                        help="Cast profile or a single speech renderer directory")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error(f"{args.db} not found: start the backend once to create it.")
    if os.name == "nt":
        # The speech runtimes load CUDA libraries that ship inside torch on Windows.
        import torch
        os.environ["PATH"] = str(Path(torch.__file__).parent / "lib") + os.pathsep + os.environ["PATH"]

    import seed_demo
    from audio_assembler import AudioAssembler
    from recording_room import RecordingRoom
    from state_manager import StateManager

    sm = StateManager(str(args.db))
    project_id = seed_demo._upsert_project(sm)
    chapter_id, _ = seed_demo._upsert_chapter(sm, project_id)
    sm.save_diarized_lines(chapter_id, seed_demo._LINES)
    print(f"[demo] {len(seed_demo._LINES)} lines seeded into chapter {chapter_id}")

    with RecordingRoom(sm, ROOT / "data/audio", args.cast) as room:
        def progress(done: int, total: int, line) -> None:
            line = dict(line)
            print(f"[demo] {done}/{total}  {line.get('speaker')}: {(line.get('text') or '')[:60]}", flush=True)
        room.process_chapter(chapter_id, progress_callback=progress)
    chapter = sm.get_chapter_by_id(chapter_id)
    if chapter["status"] == "error":
        print(f"[demo] recording failed: {chapter['error_message']}")
        return 1

    score = ROOT / "data/audio" / f"ch_{chapter_id:04d}" / "score.json"
    out = AudioAssembler(sm, str(ROOT / "data/output"),
                         cfg={"output_format": "mp3", "score_path": str(score)}).assemble_chapter(chapter_id)
    print(f"[demo] done: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
