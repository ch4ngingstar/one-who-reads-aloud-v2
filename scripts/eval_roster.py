"""
Post-Volume-9 roster audit — which speaking characters in the EPUB are NOT
covered by the diarizer roster (DEFAULT_SPEAKERS) or its aliases (SPEAKER_ALIASES)?

Parses the EPUB, extracts dialogue-attribution names heuristically (capitalized
name adjacent to a speech verb in a paragraph that contains a quote), ranks them
by frequency, and flags the uncovered ones. Grounded in the actual source text,
not lore memory. Output drives Phase-2 roster expansion + voice registration.

Read-only. Run from repo root:
    python scripts/eval_roster.py --epub <file.epub> --after-index 0 --top 40
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from eval_common import ROOT, REPORTS_DIR, write_csv

SPEECH_VERBS = (
    "said|asked|replied|answered|whispered|muttered|shouted|cried|exclaimed|"
    "snapped|growled|murmured|sighed|called|continued|added|declared|demanded|"
    "hissed|roared|breathed|gasped|stated|spoke|repeated|observed|remarked|"
    "retorted|countered|chuckled|laughed|screamed|yelled|grumbled|nodded"
)
# name = one or two Capitalized tokens
_NAME = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
_VERB_THEN_NAME = re.compile(rf"\b(?:{SPEECH_VERBS})\s+{_NAME}")
_NAME_THEN_VERB = re.compile(rf"{_NAME}\s+(?:{SPEECH_VERBS})\b")
_QUOTE = re.compile(r'["“”]')

# Capitalized tokens that are not character names (sentence starters / pronouns).
_STOP = {
    "The", "He", "She", "They", "It", "And", "But", "His", "Her", "Their", "A",
    "An", "I", "We", "You", "There", "Then", "When", "As", "If", "So", "That",
    "This", "What", "Why", "How", "Who", "Yes", "No", "Of", "In", "On", "At",
    "For", "With", "To", "Not", "Now", "Here", "Still", "Even", "Just", "All",
}


def extract_speakers(text: str) -> Counter:
    """Count dialogue-attribution names in paragraphs that contain a quote."""
    counts: Counter = Counter()
    for para in re.split(r"\n\s*\n", text):
        if not _QUOTE.search(para):
            continue
        for m in _VERB_THEN_NAME.findall(para):
            _tally(counts, m)
        for m in _NAME_THEN_VERB.findall(para):
            _tally(counts, m)
    return counts


def _tally(counts: Counter, name: str) -> None:
    name = name.strip()
    first = name.split()[0]
    if first in _STOP or len(name) < 2:
        return
    counts[name] += 1


def known_coverage():
    """Return (covered_set, alias_to_canonical) for membership checks.
    covered = roster + alias keys + structural speakers, all Title-cased."""
    from llm_director import DEFAULT_SPEAKERS, SYSTEM_SPEAKER
    from tts_engine import SPEAKER_ALIASES

    covered = {s.strip().title() for s in DEFAULT_SPEAKERS}
    covered |= {k.strip().title() for k in SPEAKER_ALIASES}
    covered |= {"Narrator", "Unknown", SYSTEM_SPEAKER.title()}
    return covered, SPEAKER_ALIASES


def audit(text: str) -> dict:
    """Rank extracted speakers; split into covered vs uncovered."""
    counts = extract_speakers(text)
    covered, _ = known_coverage()
    rows = []
    for name, n in counts.most_common():
        is_covered = name.strip().title() in covered
        rows.append({"name": name, "count": n,
                     "covered": "yes" if is_covered else ""})
    uncovered = [r for r in rows if not r["covered"]]
    return {"rows": rows, "uncovered": uncovered, "total_names": len(rows)}


def _load_chapter_texts(epub: Path, after_index: int) -> str:
    from epub_parser import parse_epub

    book = parse_epub(epub)
    parts = []
    for ch in book.chapters:
        if ch.chapter_index < after_index:
            continue
        for chunk in ch.chunks:
            parts.append(chunk.text)
    return "\n\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit EPUB speakers vs diarizer roster.")
    ap.add_argument("--epub", default=None, help="EPUB path (default: auto-detect under repo)")
    ap.add_argument("--after-index", type=int, default=0,
                    help="only chapters with chapter_index >= this (post-vol-9 slice)")
    ap.add_argument("--top", type=int, default=40, help="print this many uncovered names")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    epub = Path(args.epub) if args.epub else None
    if epub is None:
        candidates = list(ROOT.glob("**/*.epub"))
        if not candidates:
            print("[eval] no EPUB found — pass --epub.", file=sys.stderr)
            sys.exit(2)
        epub = candidates[0]
    if not epub.exists():
        print(f"[eval] EPUB not found: {epub}", file=sys.stderr)
        sys.exit(2)

    print(f"[eval] parsing {epub.name} (chapters >= index {args.after_index})...")
    text = _load_chapter_texts(epub, args.after_index)
    result = audit(text)

    print(f"[eval] {result['total_names']} distinct attributed names; "
          f"{len(result['uncovered'])} UNCOVERED by roster/aliases:\n")
    for r in result["uncovered"][: args.top]:
        print(f"  {r['count']:>4}  {r['name']}")

    out = args.out or str(REPORTS_DIR / "eval_roster.csv")
    write_csv(Path(out), result["rows"], ["name", "count", "covered"])
    print(f"\n[eval] wrote {out}")


if __name__ == "__main__":
    main()
