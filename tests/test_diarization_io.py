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


# ── T3: build_export + system prompt ────────────────────────────────────────

def test_build_export_payload():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"We move at dawn." Nephis turned away.'])
    payload = dio.build_export(sm, ch_id)

    assert payload["chapter_id"] == ch_id
    assert payload["chapter_index"] == 7
    assert payload["title"] == "Chapter 7"
    assert "Narrator" in payload["speakers"] and "Unknown" in payload["speakers"]
    assert payload["speakers"][0] == "Narrator"
    segs = payload["segments"]
    assert [s["i"] for s in segs] == list(range(len(segs)))
    assert all({"i", "kind", "text"} == set(s) for s in segs)
    # text is verbatim-from-EPUB (a known fragment survives)
    assert any("We move at dawn" in s["text"] for s in segs)
    print("  PASS test_build_export_payload")


def test_build_export_unknown_chapter_raises():
    sm = _tmp_sm()
    try:
        dio.build_export(sm, 999)
        assert False, "expected ValueError for unknown chapter"
    except ValueError:
        pass
    print("  PASS test_build_export_unknown_chapter_raises")


def test_system_prompt_text_has_roster_and_schema():
    txt = dio.build_system_prompt_text()
    assert "Narrator" in txt and "Unknown" in txt
    assert '"labels"' in txt and '"speaker"' in txt and '"emotion"' in txt
    for emo in EMOTION_VOCAB:
        assert emo in txt
    print("  PASS test_system_prompt_text_has_roster_and_schema")


TESTS = [
    test_segment_chapter_global_indices,
    test_build_export_payload,
    test_build_export_unknown_chapter_raises,
    test_system_prompt_text_has_roster_and_schema,
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
