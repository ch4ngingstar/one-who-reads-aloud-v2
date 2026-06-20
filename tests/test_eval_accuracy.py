"""
Tests for scripts/eval_accuracy.py — normalize + WER scoring loop.
ASR (faster-whisper) and jiwer are injected/monkeypatched, so this is GPU- and
dependency-free. Run: python tests/test_eval_accuracy.py
"""

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_accuracy
from state_manager import StateManager


def _tmp_sm() -> StateManager:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _silent_wav(path: Path, ms=80, sr=16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * ms / 1000))


def _seed_chapter_with_lines(sm, texts):
    pid = sm.seed_project({
        "source_epub": "shadow_slave.epub", "total_chapters": 1,
        "chapters": [{"chapter_index": 0, "title": "Ch", "chunks": [
            {"chunk_index": 0, "text": "x", "word_count": 1}]}],
    })
    cid = sm.get_all_chapters(pid)[0]["id"]
    sm.save_diarized_lines(cid, [
        {"line_index": i, "speaker": "Narrator", "text": t, "emotion": "neutral"}
        for i, t in enumerate(texts)])
    return cid


def test_normalize_strips_punct_and_case():
    assert eval_accuracy.normalize("Hello, World!") == "hello world"
    assert eval_accuracy.normalize("  A—B  ") == "a b"


def test_score_chapter_perfect_and_flagged_and_missing():
    sm = _tmp_sm()
    cid = _seed_chapter_with_lines(sm, ["The door opened", "He ran away", "No audio here"])
    lines = sm.get_lines_for_chapter(cid)

    # lines 0,1 get audio; line 2 has none → counted as missing
    for ln in lines[:2]:
        wav = Path(tempfile.gettempdir()) / f"acc_{ln['id']}.wav"
        _silent_wav(wav)
        sm.mark_line_tts_done(ln["id"], str(wav))

    # ASR: line 0 transcribes perfectly, line 1 returns garbage
    def fake_transcribe(path):
        return "the door opened" if path.endswith(f"acc_{lines[0]['id']}.wav") else "zzz"

    # avoid jiwer: 0 error iff strings equal
    eval_accuracy._wer_cer = lambda ref, hyp: ((0.0, 0.0) if ref == hyp else (1.0, 1.0))

    res = eval_accuracy.score_chapter(sm, cid, fake_transcribe, wer_threshold=0.4)
    assert res["n_scored"] == 2
    assert res["n_missing"] == 1
    assert res["mean_wer"] == 0.5      # one perfect, one wrong
    assert res["n_flagged"] == 1


def test_wer_cer_real_jiwer_if_available():
    try:
        import jiwer  # noqa: F401
    except Exception:
        print("    (jiwer not installed — skipping real WER check)")
        return
    wer, cer = eval_accuracy._wer_cer("the cat sat", "the cat sat")
    assert wer == 0.0 and cer == 0.0
    wer2, _ = eval_accuracy._wer_cer("the cat sat", "the dog sat")
    assert wer2 > 0.0


TESTS = [
    test_normalize_strips_punct_and_case,
    test_score_chapter_perfect_and_flagged_and_missing,
    test_wer_cer_real_jiwer_if_available,
]

if __name__ == "__main__":
    print("Running eval_accuracy tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
