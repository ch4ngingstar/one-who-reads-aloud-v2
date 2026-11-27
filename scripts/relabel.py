"""Label chapters with the local Qwen labeller, resumably, one JSON file per chapter.

    python scripts/relabel.py --chapters 1697 1736            # by real chapter number
    python scripts/relabel.py --from 1841 --to 1850           # a short range (power cuts!)
    python scripts/relabel.py --chapters 1697 --out data/labels/try --no-emotion

Text always comes from the EPUB (volumes 8-9 lost ~15% of paragraphs in the database).
Finished chapters are skipped, so an interrupted run resumes where it stopped; a chapter
is written atomically only once it is complete. Nothing is written to the database here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book_text import chapter_paragraphs, chapter_text  # noqa: E402
from character_bible import Bible  # noqa: E402
from label_import import text_hash  # noqa: E402
from qwen_labeller import DEFAULT_MODEL, LABELLER_VERSION, Labeller, LocalModel  # noqa: E402
from segmenter import segment_chunk  # noqa: E402

DB = ROOT / "src" / "data" / "pipeline.db"
OUT = ROOT / "data" / "labels" / LABELLER_VERSION
TAIL_PARAGRAPHS = 14


def chapters_to_label(con, numbers=None, first=None, last=None) -> "list[tuple[int, int, str]]":
    rows = con.execute("select id, chapter_number, display_title from chapters "
                       "where kind = 'chapter' and chapter_number is not null order by chapter_number").fetchall()
    picked = [r for r in rows if (numbers and r[1] in numbers)
              or (first is not None and first <= r[1] <= (last if last is not None else 10**9))]
    return [(r[0], r[1], r[2] or f"Chapter {r[1]}") for r in picked]


def previous_tail(con, chapter_id: int) -> "list[str]":
    project, index = con.execute("select project_id, chapter_index from chapters where id = ?", (chapter_id,)).fetchone()
    row = con.execute("select id from chapters where project_id = ? and chapter_index = ? and kind = 'chapter'",
                      (project, index - 1)).fetchone()
    if not row:
        return []
    try:
        return chapter_paragraphs(con, row[0])[-TAIL_PARAGRAPHS:]
    except LookupError:
        return []


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chapters", type=int, nargs="+")
    parser.add_argument("--from", dest="first", type=int)
    parser.add_argument("--to", dest="last", type=int)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--no-emotion", action="store_true")
    parser.add_argument("--think-all", action="store_true", help="Reason on every line (slower)")
    parser.add_argument("--force", action="store_true", help="Relabel chapters that already have a file")
    args = parser.parse_args(argv)
    if not args.chapters and args.first is None:
        parser.error("give --chapters or --from/--to")

    con = sqlite3.connect(str(DB))
    todo = chapters_to_label(con, set(args.chapters or []), args.first, args.last)
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [c for c in todo if args.force or not (args.out / f"ch_{c[1]}.json").exists()]
    if not todo:
        print("Nothing to label.")
        return
    bible = Bible.load()
    model = LocalModel(args.model)
    labeller = Labeller(model, bible, emotions=not args.no_emotion, always_think=args.think_all)
    try:
        for chapter_id, number, title in todo:
            started = time.time()
            try:
                text = chapter_text(con, chapter_id)
                segments = segment_chunk(text, include_paragraph=True)
                labels = labeller.label_chapter(segments, title, previous_tail(con, chapter_id))
            except (LookupError, ValueError) as error:
                # One unreadable or oversized chapter must not stop a long batch.
                print(f"ch {number}: SKIPPED - {error}", flush=True)
                continue
            seconds = time.time() - started
            record = {"chapter": number, "chapter_id": chapter_id, "title": title, "labeller": LABELLER_VERSION,
                      "labelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "seconds": round(seconds, 1), "segments": len(segments), "text_sha256": text_hash(text),
                      "labels": labels}
            target = args.out / f"ch_{number}.json"
            partial = target.with_suffix(".part")
            partial.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            partial.replace(target)
            flagged = sum(1 for label in labels if label.get("review"))
            print(f"ch {number}: {len(labels)} lines, {flagged} flagged, {seconds:.0f}s", flush=True)
    finally:
        model.close()


if __name__ == "__main__":
    main()
