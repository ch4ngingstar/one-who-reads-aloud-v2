"""
Tests for scripts/eval_emotion.py — delta math, inert flagging, and that the
neutral baseline synthesizes with emo_vector=None. librosa/TTS are never loaded;
feature extraction is monkeypatched and the engine is a fake. GPU-free.
Run: python tests/test_eval_emotion.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_emotion


def test_aggregate_means():
    feats = [{k: 2.0 for k in eval_emotion.FEATURES},
             {k: 4.0 for k in eval_emotion.FEATURES}]
    agg = eval_emotion.aggregate(feats)
    assert all(agg[k] == 3.0 for k in eval_emotion.FEATURES)


def test_deltas_vs_neutral():
    neutral = {"f0_mean": 100.0, "f0_std": 10.0, "rms_mean": 0.10,
               "duration": 1.0, "rate": 10.0}
    tag_means = {"angry": {"f0_mean": 150.0, "f0_std": 20.0, "rms_mean": 0.20,
                           "duration": 1.0, "rate": 12.0}}
    d = eval_emotion.deltas_vs_neutral(tag_means, neutral)["angry"]
    assert d["f0_mean"] == 50.0
    assert abs(d["f0_mean_rel"] - 0.5) < 1e-9
    assert abs(d["rms_mean_rel"] - 1.0) < 1e-9


def test_flag_inert_detects_no_change():
    neutral = {"f0_mean": 100.0, "f0_std": 10.0, "rms_mean": 0.10,
               "duration": 1.0, "rate": 10.0}
    means = {
        # well within every band → inert
        "cold": {"f0_mean": 101.0, "f0_std": 11.0, "rms_mean": 0.103,
                 "duration": 1.0, "rate": 10.1},
        # clearly moves f0 → active
        "angry": {"f0_mean": 140.0, "f0_std": 30.0, "rms_mean": 0.18,
                  "duration": 1.0, "rate": 13.0},
    }
    delta = eval_emotion.deltas_vs_neutral(means, neutral)
    inert = eval_emotion.flag_inert(delta)
    assert "cold" in inert
    assert "angry" not in inert


def test_synthesize_matrix_neutral_uses_none_vector():
    calls = []

    class FakeEngine:
        def _synthesize(self, text, ref, emo_vector=None, emo_alpha=0.0):
            calls.append((text, emo_vector, emo_alpha))
            return b"RIFFfake"

    out = Path(tempfile.mkdtemp())
    result = eval_emotion.synthesize_matrix(
        FakeEngine(), "ref.wav", ["A sentence."], out)

    # every tag produced one clip file
    from tts_engine import INDEXTTS2_EMOTION_VECTORS
    assert set(result) == set(INDEXTTS2_EMOTION_VECTORS)
    assert (out / "neutral" / "probe_00.wav").exists()

    neutral_calls = [c for c in calls if c[1] is None]
    nonneutral_calls = [c for c in calls if c[1] is not None]
    assert neutral_calls, "neutral must pass emo_vector=None"
    assert nonneutral_calls, "non-neutral tags must pass a vector"


def test_build_report_with_mocked_features():
    # canned features: 'cold' ~ neutral (inert), 'angry' far from neutral
    canned = {
        "neutral": {"f0_mean": 100, "f0_std": 10, "rms_mean": 0.10, "duration": 1, "rate": 10},
        "cold":    {"f0_mean": 101, "f0_std": 10, "rms_mean": 0.101, "duration": 1, "rate": 10},
        "angry":   {"f0_mean": 160, "f0_std": 40, "rms_mean": 0.25, "duration": 1, "rate": 14},
    }
    # map a clip path back to its tag via the parent dir name
    eval_emotion.extract_features = lambda path, n: canned[Path(path).parent.name]
    synth = {tag: [(str(Path(tag) / "probe_00.wav"), 5)] for tag in canned}
    report = eval_emotion.build_report(synth)
    assert "cold" in report["inert_tags"]
    assert "angry" not in report["inert_tags"]


TESTS = [
    test_aggregate_means,
    test_deltas_vs_neutral,
    test_flag_inert_detects_no_change,
    test_synthesize_matrix_neutral_uses_none_vector,
    test_build_report_with_mocked_features,
]

if __name__ == "__main__":
    print("Running eval_emotion tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
