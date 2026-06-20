"""
Tests for scripts/eval_speaker.py — cosine + per-line similarity loop.
resemblyzer is injected (fake embedder); GPU-free. Run: python tests/test_eval_speaker.py
"""

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_speaker
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


def test_cosine():
    assert abs(eval_speaker.cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(eval_speaker.cosine([1, 0], [0, 1]) - 0.0) < 1e-9


def test_emo_alpha_lookup():
    assert eval_speaker._emo_alpha("neutral") == 0.0
    assert eval_speaker._emo_alpha("angry") > 0.0


def test_score_chapter_similarity_and_flag():
    sm = _tmp_sm()
    pid = sm.seed_project({
        "source_epub": "shadow_slave.epub", "total_chapters": 1,
        "chapters": [{"chapter_index": 0, "title": "Ch", "chunks": [
            {"chunk_index": 0, "text": "x", "word_count": 1}]}],
    })
    cid = sm.get_all_chapters(pid)[0]["id"]
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "Sunny", "text": "Hello", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny", "text": "Run", "emotion": "angry"},
    ])
    lines = sm.get_lines_for_chapter(cid)
    tmp = Path(tempfile.mkdtemp())
    refwav = tmp / "sunny_ref.wav"; _silent_wav(refwav)
    w0 = tmp / "l0.wav"; _silent_wav(w0)
    w1 = tmp / "l1.wav"; _silent_wav(w1)
    sm.mark_line_tts_done(lines[0]["id"], str(w0))
    sm.mark_line_tts_done(lines[1]["id"], str(w1))
    sm.set_voice("Sunny", str(refwav))
    voice_map = sm.get_voice_map()

    # fake embeddings keyed by filename: ref==l0 (sim 1), l1 orthogonal (sim 0)
    vecs = {"sunny_ref.wav": [1.0, 0.0], "l0.wav": [1.0, 0.0], "l1.wav": [0.0, 1.0]}
    embed = lambda path: vecs[Path(path).name]

    res = eval_speaker.score_chapter(sm, cid, voice_map, embed, sim_threshold=0.75)
    assert res["n_scored"] == 2
    by_idx = {r["line_index"]: r for r in res["rows"]}
    assert abs(by_idx[0]["similarity"] - 1.0) < 1e-6 and by_idx[0]["flagged"] == ""
    assert abs(by_idx[1]["similarity"] - 0.0) < 1e-6 and by_idx[1]["flagged"] == "yes"
    assert "Sunny" in res["per_speaker"]


TESTS = [test_cosine, test_emo_alpha_lookup, test_score_chapter_similarity_and_flag]

if __name__ == "__main__":
    print("Running eval_speaker tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
