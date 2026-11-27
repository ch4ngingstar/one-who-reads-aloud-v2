"""Voice Foundry WS1 -- backfill `lines.kind` by deterministic segmenter replay.

`segmenter.segment_chunk()` computes dialogue/thought/system/prose for every segment
and then throws it away: `lines` never had a `kind` column. Because `chunks.text`
survives verbatim and diarization is label-only (the LLM never reproduces text), the
kind is fully recoverable by replaying the segmenter -- no LLM, no re-diarization.

SAFETY CONTRACT: a chapter is backfilled only if the replay reconciles EXACTLY against
the stored lines -- same count, same text, same order. Any mismatch flags the chapter
and skips it whole. A partially-correct kind column is worse than a NULL one, because
NULL is honest about not knowing. An earlier survey found ~99.8% alignment with ~65
lines of drift, so mismatches are expected and must not be papered over.

Usage:
    python scripts/backfill_line_kind.py            # dry run, reports only
    python scripts/backfill_line_kind.py --apply    # writes kinds for clean chapters
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from segmenter import segment_chunk  # noqa: E402

DB_PATH = SRC / "data" / "pipeline.db"

# Whitespace is the only difference tolerated when matching replayed segment text to
# stored line text. Anything else means the replay and the stored lines genuinely
# disagree about where a boundary fell, which is exactly what must be flagged.
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def replay_chapter(conn: sqlite3.Connection, chapter_id: int) -> list:
    """Re-derive the ordered segment list for a chapter from chunks.text."""
    rows = conn.execute(
        "SELECT text FROM chunks WHERE chapter_id=? ORDER BY chunk_index", (chapter_id,)
    ).fetchall()
    segments = []
    for (text,) in rows:
        segments.extend(segment_chunk(text))
    return segments


def reconcile(segments: list, lines: list) -> "tuple[bool, str]":
    """Return (ok, reason). Text must match one-for-one and in order."""
    if len(segments) != len(lines):
        return False, f"count {len(segments)} replayed vs {len(lines)} stored"
    for i, (seg, ln) in enumerate(zip(segments, lines)):
        if norm(seg["text"]) != norm(ln[2]):
            return False, f"text differs at line_index {ln[1]} (position {i})"
    return True, "exact"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write kinds for chapters that reconcile exactly")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"DB not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(lines)")]
    if "kind" not in cols:
        print("ERROR: lines.kind does not exist. Start the app/StateManager once so the\n"
              "       migration in _init_db runs, then re-run this script.")
        return 1

    chapter_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT chapter_id FROM lines ORDER BY chapter_id")]
    if not chapter_ids:
        print("No chapters have lines -- nothing to backfill.")
        return 0

    clean, flagged, kind_tally = [], [], Counter()
    total_lines = written = 0

    for cid in chapter_ids:
        lines = conn.execute(
            "SELECT id, line_index, text FROM lines WHERE chapter_id=? ORDER BY line_index",
            (cid,),
        ).fetchall()
        total_lines += len(lines)
        segments = replay_chapter(conn, cid)
        ok, reason = reconcile(segments, lines)
        if not ok:
            flagged.append((cid, reason))
            continue
        clean.append(cid)
        for seg in segments:
            kind_tally[seg["kind"]] += 1
        if args.apply:
            conn.executemany(
                "UPDATE lines SET kind=? WHERE id=?",
                [(seg["kind"], ln[0]) for seg, ln in zip(segments, lines)],
            )
            written += len(lines)

    if args.apply:
        conn.commit()

    n = len(chapter_ids)
    pct = 100.0 * len(clean) / n if n else 0.0
    print("=" * 72)
    print(f"{'BACKFILL APPLIED' if args.apply else 'DRY RUN -- nothing written'}")
    print("=" * 72)
    print(f"chapters with lines : {n}")
    print(f"reconciled exactly  : {len(clean)}  ({pct:.1f}%)")
    print(f"flagged / skipped   : {len(flagged)}")
    print(f"lines examined      : {total_lines:,}")
    if args.apply:
        print(f"lines written       : {written:,}")

    if kind_tally:
        print("\nkind distribution over reconciled chapters:")
        tot = sum(kind_tally.values())
        for k, c in kind_tally.most_common():
            print(f"  {k:<10}{c:>8,}  {100.0 * c / tot:>5.1f}%")

    if flagged:
        print(f"\nFLAGGED CHAPTERS (left NULL -- inspect before trusting):")
        for cid, reason in flagged[:25]:
            print(f"  chapter_id {cid:<6} {reason}")
        if len(flagged) > 25:
            print(f"  ... and {len(flagged) - 25} more")

    if not args.apply:
        print("\nRe-run with --apply to write. Rollback: ALTER TABLE lines DROP COLUMN kind")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
