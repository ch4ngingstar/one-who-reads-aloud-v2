"""Store labelled chapters in the database (complete text + speakers + emotions).

    python scripts/import_labels.py --from 1841 --to 1850 --dry-run   # what would change
    python scripts/import_labels.py --from 1841 --to 1850             # do it
    python scripts/import_labels.py --chapters 1697 --labels data/labels/qwen-v1

The database is backed up once per run before anything is written. Each chapter is
stored in its own transaction, so an interrupted run leaves every chapter either fully
old or fully new. Imported chapters become 'diarized': a chapter that already had an
MP3 keeps it until it is re-rendered. Hand-locked speakers are kept.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from label_import import StaleLabels, import_chapter  # noqa: E402
from qwen_labeller import LABELLER_VERSION  # noqa: E402
from state_manager import StateManager  # noqa: E402

DB = ROOT / "src" / "data" / "pipeline.db"
LABELS = ROOT / "data" / "labels" / f"{LABELLER_VERSION}-checked"  # after Gemma's second opinion


def wanted(record: dict, numbers, first, last) -> bool:
    number = record["chapter"]
    return (numbers and number in numbers) or (first is not None and first <= number <= (last or 10**9))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chapters", type=int, nargs="+")
    parser.add_argument("--from", dest="first", type=int)
    parser.add_argument("--to", dest="last", type=int)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.chapters and args.first is None:
        parser.error("give --chapters or --from/--to")

    records = []
    for path in sorted(args.labels.glob("ch_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            print(f"skip {path.name}: unreadable ({error})")
            continue
        if wanted(record, set(args.chapters or []), args.first, args.last):
            records.append(record)
    if not records:
        print("No labelled chapters in that range.")
        return
    if args.dry_run:
        for record in records:
            flagged = sum(1 for label in record["labels"] if label.get("review"))
            print(f"would import ch {record['chapter']}: {len(record['labels'])} labelled lines, {flagged} flagged")
        return
    backup = DB.with_name(f"pipeline.db.bak-import-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    shutil.copy2(DB, backup)
    print(f"Backup: {backup.name}")
    sm = StateManager(DB)
    voices = sm.get_voice_map()
    con = sqlite3.connect(str(DB))
    for record in sorted(records, key=lambda r: r["chapter"]):
        try:
            count = import_chapter(sm, con, record, voices)
        except (StaleLabels, LookupError, ValueError) as error:
            print(f"ch {record['chapter']}: NOT imported - {error}")
            continue
        print(f"ch {record['chapter']}: {count} lines stored")


if __name__ == "__main__":
    main()
