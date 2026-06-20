"""
Tests for scripts/eval_common.py — project/chapter resolution + WAV lookup.
Run: python tests/test_eval_common.py   (no GPU, temp SQLite)
"""

import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_common
from state_manager import StateManager


def _tmp_sm() -> StateManager:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed(sm) -> int:
    return sm.seed_project({
        "source_epub": "shadow_slave.epub",
        "total_chapters": 1,
        "chapters": [{"chapter_index": 5, "title": "Ch", "chunks": [
            {"chunk_index": 0, "text": "word " * 10, "word_count": 10}]}],
    })


def _silent_wav(path: Path, ms=80, sr=16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * ms / 1000))


def test_chapter_index_mapping():
    sm = _tmp_sm(); pid = _seed(sm)
    cid = eval_common.chapter_id_for_index(sm, pid, 5)
    assert cid is not None
    assert eval_common.chapter_id_for_index(sm, pid, 999) is None


def test_resolve_chapter_ids_by_index_and_default():
    sm = _tmp_sm(); pid = _seed(sm)
    cid = eval_common.chapter_id_for_index(sm, pid, 5)
    sm.save_diarized_lines(cid, [{"line_index": 0, "speaker": "Narrator",
                                  "text": "Hi", "emotion": "neutral"}])
    assert eval_common.resolve_chapter_ids(sm, pid, [5], by_index=True) == [cid]
    # default: every chapter with lines
    assert eval_common.resolve_chapter_ids(sm, pid, None, by_index=False) == [cid]


def test_resolve_line_wav_prefers_db_path_then_fallback():
    sm = _tmp_sm(); pid = _seed(sm)
    cid = eval_common.chapter_id_for_index(sm, pid, 5)
    sm.save_diarized_lines(cid, [{"line_index": 0, "speaker": "Narrator",
                                  "text": "Hi", "emotion": "neutral"}])
    line = sm.get_lines_for_chapter(cid)[0]

    # No audio yet → None
    assert eval_common.resolve_line_wav(line, cid) is None

    # DB audio_path (absolute) wins
    wav = Path(tempfile.gettempdir()) / "eval_common_line.wav"
    _silent_wav(wav)
    sm.mark_line_tts_done(line["id"], str(wav))
    line2 = sm.get_lines_for_chapter(cid)[0]
    found = eval_common.resolve_line_wav(line2, cid)
    assert found is not None and Path(found).exists()

    # Conventional fallback when no DB path
    audio_root = Path(tempfile.mkdtemp())
    conv = audio_root / f"ch_{cid:04d}" / "line_0000.wav"
    _silent_wav(conv)
    found2 = eval_common.resolve_line_wav(line, cid, audio_root=audio_root)
    assert found2 == conv


TESTS = [
    test_chapter_index_mapping,
    test_resolve_chapter_ids_by_index_and_default,
    test_resolve_line_wav_prefers_db_path_then_fallback,
]

if __name__ == "__main__":
    print("Running eval_common tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t(); passed += 1; print(f"  ok   {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {t.__name__}: {e}"); traceback.print_exc(); failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
