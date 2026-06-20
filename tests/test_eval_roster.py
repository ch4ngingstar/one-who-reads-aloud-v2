"""
Tests for scripts/eval_roster.py — attribution extraction + coverage diff.
Pure text heuristics; imports llm_director/tts_engine constants (no GPU).
Run: python tests/test_eval_roster.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_roster

SAMPLE = (
    '"We should go," said Gorm. The wind howled across the plain.\n\n'
    'Sunny said, "Not yet." He waited for a long moment.\n\n'
    '"Leave me alone," whispered Zalivia, stepping back.\n\n'
    'There was no quote in this paragraph so it must be ignored entirely.\n\n'
    '"Hello," said The soldier, lowering his blade.'
)


def test_extract_speakers_counts_and_quote_gating():
    counts = eval_roster.extract_speakers(SAMPLE)
    assert counts["Gorm"] == 1
    assert counts["Sunny"] == 1
    assert counts["Zalivia"] == 1
    # "The soldier" → first token is a stopword, must not be counted
    assert "The" not in counts and "The Soldier" not in counts
    # paragraph without a quote contributes nothing
    assert "There" not in counts


def test_audit_marks_known_vs_uncovered():
    res = eval_roster.audit(SAMPLE)
    by_name = {r["name"]: r for r in res["rows"]}
    assert by_name["Sunny"]["covered"] == "yes"          # in DEFAULT_SPEAKERS
    assert by_name["Gorm"]["covered"] == ""              # not in roster/aliases
    uncovered_names = {r["name"] for r in res["uncovered"]}
    assert "Gorm" in uncovered_names and "Zalivia" in uncovered_names
    assert "Sunny" not in uncovered_names


def test_known_coverage_includes_structural_speakers():
    covered, aliases = eval_roster.known_coverage()
    assert "Narrator" in covered and "Unknown" in covered
    assert isinstance(aliases, dict)


TESTS = [
    test_extract_speakers_counts_and_quote_gating,
    test_audit_marks_known_vs_uncovered,
    test_known_coverage_includes_structural_speakers,
]

if __name__ == "__main__":
    print("Running eval_roster tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
