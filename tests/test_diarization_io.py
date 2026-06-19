"""
Test suite for external diarization import (diarization_io.py).
Run: python tests/test_diarization_io.py
No GPU / no model required.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
import diarization_io as dio
from llm_director import EMOTION_VOCAB


def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_chapter(sm, text_chunks):
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 7,
            "title": "Chapter 7",
            "chunks": [
                {"chunk_index": i, "text": t, "word_count": len(t.split())}
                for i, t in enumerate(text_chunks)
            ],
        }],
    }
    pid = sm.seed_project(book)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    return pid, ch_id


# ── T2: segment_chapter ─────────────────────────────────────────────────────

def test_segment_chapter_global_indices():
    sm = _tmp_sm()
    # two chunks, each yields >=1 segment; indices must be 0..N-1 across both
    _, ch_id = _seed_chapter(sm, ["The hall was silent.", '"Move out," she said.'])
    segs = dio.segment_chapter(sm, ch_id)
    assert [s["index"] for s in segs] == list(range(len(segs))), \
        "chapter-global indices must be contiguous 0..N-1"
    assert len(segs) >= 2, "expected at least one segment per chunk"
    assert all({"index", "kind", "text"} <= set(s) for s in segs)
    print("  PASS test_segment_chapter_global_indices")


TESTS = [
    test_segment_chapter_global_indices,
]


if __name__ == "__main__":
    print("Running diarization_io tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{'=' * 40}\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
