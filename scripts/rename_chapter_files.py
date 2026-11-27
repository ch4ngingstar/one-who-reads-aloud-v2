"""Rename finished chapter files from database ids to the book's real chapters.

    python scripts/rename_chapter_files.py              # show what would move (nothing changes)
    python scripts/rename_chapter_files.py --apply      # move files + update the database
    python scripts/rename_chapter_files.py --undo data/output/rename-log-<time>.json

"ch_0407.mp3" becomes "data/output/Shadow Slave, Volume 9/1994 - Call to Arms.mp3", the same
names new renders get. Each move (with its .performance.json timing sidecar) is recorded in a
log so --undo restores every file and database path exactly. Nothing is ever overwritten:
a destination that already exists is reported and skipped.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chapter_titles import book_folder, chapter_filename, identify, safe_name  # noqa: E402
from state_manager import StateManager, _resolve_stored_path  # noqa: E402

DB = ROOT / "src/data/pipeline.db"
OUTPUT = ROOT / "data/output"


def target_for(chapter, project_name):
    identity = identify(chapter["title"] or "")
    current = _resolve_stored_path(chapter["output_audio_path"])
    folder = OUTPUT / book_folder(project_name)
    if identity.number is None and identity.kind != "front":
        return folder / f"{safe_name(identity.display)} [{chapter['id']}]{current.suffix}"
    return folder / chapter_filename(identity, current.suffix)


def plan(db):
    StateManager(str(db))  # make sure the chapter identity columns exist
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    projects = {row["id"]: row["name"] for row in con.execute("select id, name from projects")}
    moves, problems = [], []
    for chapter in con.execute("select id, project_id, title, output_audio_path from chapters "
                               "where output_audio_path is not null order by project_id, chapter_index"):
        current = _resolve_stored_path(chapter["output_audio_path"])
        if not current.is_file():
            problems.append(f"chapter {chapter['id']}: file missing ({current})")
            continue
        target = target_for(chapter, projects.get(chapter["project_id"], ""))
        if current.resolve() == target.resolve():
            continue
        if target.exists():
            problems.append(f"chapter {chapter['id']}: {target} already exists; left as is")
            continue
        moves.append({"chapter_id": chapter["id"], "old": str(current), "new": str(target)})
    return moves, problems


def move_with_sidecar(old, new):
    old, new = Path(old), Path(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    sheet = old.with_suffix(".performance.json")
    if sheet.is_file():
        shutil.move(str(sheet), str(new.with_suffix(".performance.json")))


def apply(db, moves):
    con = sqlite3.connect(str(db))
    log = OUTPUT / f"rename-log-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    done = []
    try:
        for move in moves:
            move_with_sidecar(move["old"], move["new"])
            with con:
                con.execute("update chapters set output_audio_path = ? where id = ?", (move["new"], move["chapter_id"]))
            done.append(move)
    finally:
        # Written even if a move fails midway, so --undo can reverse exactly what happened.
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
    return log, done


def undo(db, log_path):
    con = sqlite3.connect(str(db))
    moves = json.loads(Path(log_path).read_text(encoding="utf-8"))
    for move in reversed(moves):
        if Path(move["new"]).is_file() and not Path(move["old"]).exists():
            move_with_sidecar(move["new"], move["old"])
            with con:
                con.execute("update chapters set output_audio_path = ? where id = ?", (move["old"], move["chapter_id"]))
    return len(moves)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Move the files and update the database")
    parser.add_argument("--undo", type=Path, help="Reverse a previous run using its log")
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args(argv)
    if args.undo:
        print(f"Restored {undo(args.db, args.undo)} chapter files.")
        return
    moves, problems = plan(args.db)
    for move in moves[:8]:
        print(f"{Path(move['old']).name:>22}  ->  {Path(move['new']).relative_to(ROOT)}")
    if len(moves) > 8:
        print(f"... and {len(moves) - 8} more")
    for problem in problems:
        print("!", problem)
    if not args.apply:
        print(f"{len(moves)} files would move. Nothing changed; run with --apply.")
        return
    log, done = apply(args.db, moves)
    print(f"Moved {len(done)} chapter files. Undo with: python scripts/rename_chapter_files.py --undo \"{log}\"")


if __name__ == "__main__":
    main()
