"""
Tests for scripts/eval_formatting.py — gold parsing, label comparison, resolution.
Pure functions; no GPU. Run: python tests/test_eval_formatting.py
"""

import sys
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_formatting


def test_load_gold_both_shapes():
    d = Path(tempfile.mkdtemp())
    a = d / "a.json"; a.write_text(json.dumps(
        {"labels": [{"i": 0, "speaker": "Sunny", "emotion": "angry"}]}), encoding="utf-8")
    b = d / "b.json"; b.write_text(json.dumps(
        [{"line_index": 0, "speaker": "Sunny", "emotion": "angry"}]), encoding="utf-8")
    assert eval_formatting.load_gold(a) == {0: ("Sunny", "angry")}
    assert eval_formatting.load_gold(b) == {0: ("Sunny", "angry")}


def test_compare_labels_accuracy_confusion_and_gaps():
    gold = {0: ("Sunny", "neutral"), 1: ("Nephis", "commanding"),
            2: ("Narrator", "neutral")}
    pred = {0: ("Sunny", "neutral"),        # fully correct
            1: ("Sunny", "commanding"),     # speaker wrong
            3: ("Narrator", "neutral")}     # index gap vs gold
    cmp = eval_formatting.compare_labels(pred, gold)
    assert cmp["n_shared"] == 2
    assert cmp["speaker_accuracy"] == 0.5     # 1 of 2 shared correct
    assert cmp["emotion_accuracy"] == 1.0
    assert cmp["speaker_confusion"].get("Nephis->Sunny") == 1
    assert cmp["missing_in_pred"] == [2]
    assert cmp["missing_in_gold"] == [3]
    assert any(m["line_index"] == 1 for m in cmp["mismatches"])


def test_compare_labels_normalizes_speaker_aliases():
    # 'Sky Tide' / 'Saint Tyris' are SPEAKER_ALIASES for 'Tyris' — the diarizer
    # naming the character by epithet must score as CORRECT, not a confusion.
    gold = {0: ("Tyris", "neutral"), 1: ("Tyris", "commanding")}
    pred = {0: ("Sky Tide", "neutral"), 1: ("Saint Tyris", "commanding")}
    cmp = eval_formatting.compare_labels(pred, gold)
    assert cmp["speaker_accuracy"] == 1.0, cmp["speaker_confusion"]
    assert cmp["speaker_confusion"] == {}
    assert cmp["mismatches"] == []


def test_norm_speaker_applies_alias_and_titlecase():
    assert eval_formatting._norm_speaker("sky tide") == "Tyris"
    assert eval_formatting._norm_speaker("  Narrator ") == "Narrator"
    # an unknown name passes through (title-cased), not crashing
    assert eval_formatting._norm_speaker("zxqwv") == "Zxqwv"


def test_resolution_summary_unmapped():
    labels = {0: ("Sunny", "neutral"), 1: ("Zxqwv The Unknown", "neutral")}
    voice_map = {"Sunny": {"path": "x.wav"}}   # no _default → unknown is unmapped
    summ = eval_formatting.resolution_summary(labels, voice_map)
    assert summ["counts"]["mapped"] == 1
    assert summ["counts"]["unmapped"] == 1
    assert "Zxqwv The Unknown" in summ["unmapped_speakers"]


TESTS = [
    test_load_gold_both_shapes,
    test_compare_labels_accuracy_confusion_and_gaps,
    test_compare_labels_normalizes_speaker_aliases,
    test_norm_speaker_applies_alias_and_titlecase,
    test_resolution_summary_unmapped,
]

if __name__ == "__main__":
    print("Running eval_formatting tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
