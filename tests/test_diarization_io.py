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


# ── T4: validate_labels + import_labels ─────────────────────────────────────

def _all_labels(sm, ch_id, speaker="Narrator", emotion="neutral"):
    """Synthetic labels covering every segment index for a chapter."""
    segs = dio.segment_chapter(sm, ch_id)
    return {"chapter_id": ch_id,
            "labels": [{"i": s["index"], "speaker": speaker, "emotion": emotion}
                       for s in segs]}


def test_import_round_trip_sets_diarized():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent. Dust hung in the air."])
    labels = _all_labels(sm, ch_id, speaker="Narrator", emotion="calm")

    n = dio.import_labels(sm, ch_id, labels)

    chapter = sm.get_chapter_by_id(ch_id)
    assert chapter["status"] == "diarized"
    lines = sm.get_lines_for_chapter(ch_id)
    assert len(lines) == n > 0
    assert [ln["line_index"] for ln in lines] == list(range(len(lines)))
    assert all(ln["speaker"] == "Narrator" for ln in lines)  # prose -> Narrator
    print("  PASS test_import_round_trip_sets_diarized")


def test_import_enforcement_parity_with_llm():
    """Importer and LLMDirector._merge_labels must yield identical lines."""
    from llm_director import LLMDirector, DEFAULT_SPEAKERS
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"Run!" he shouted. The shadow lunged.'])
    segs = dio.segment_chapter(sm, ch_id)
    # craft a label per segment: dialogue->Sunny, everything else->Nephis
    raw = {}
    for s in segs:
        raw[s["index"]] = ("Sunny" if s["kind"] == "dialogue" else "Nephis", "afraid")

    # LLM path (single chunk -> per-chunk index == global index, offset 0)
    director = LLMDirector(Path("fake.gguf"), sm, speakers=DEFAULT_SPEAKERS)
    expected = director._merge_labels(segs, raw, 0)

    # Importer path
    labels = {"chapter_id": ch_id,
              "labels": [{"i": s["index"],
                          "speaker": raw[s["index"]][0],
                          "emotion": raw[s["index"]][1]} for s in segs]}
    dio.import_labels(sm, ch_id, labels)
    got = [{"line_index": ln["line_index"], "speaker": ln["speaker"],
            "text": ln["text"], "emotion": ln["emotion"]}
           for ln in sm.get_lines_for_chapter(ch_id)]

    assert got == expected, f"parity broken:\n  llm={expected}\n  imp={got}"
    print("  PASS test_import_enforcement_parity_with_llm")


def test_import_stale_count_mismatch_rejected():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent. Dust hung in the air."])
    labels = _all_labels(sm, ch_id)
    labels["labels"].pop()  # one short -> stale
    try:
        dio.import_labels(sm, ch_id, labels)
        assert False, "expected stale-export rejection"
    except dio.ImportRejected as e:
        assert "re-export" in str(e).lower()
    print("  PASS test_import_stale_count_mismatch_rejected")


def test_import_index_gap_rejected():
    sm = _tmp_sm()
    # two chunks -> two prose segments, so a duplicate index is possible
    _, ch_id = _seed_chapter(sm, ["The hall was silent.", "Dust hung in the air."])
    labels = _all_labels(sm, ch_id)
    assert len(labels["labels"]) >= 2, "test needs >=2 segments"
    labels["labels"][1]["i"] = labels["labels"][0]["i"]  # duplicate index
    try:
        dio.import_labels(sm, ch_id, labels)
        assert False, "expected duplicate-index rejection"
    except dio.ImportRejected:
        pass
    print("  PASS test_import_index_gap_rejected")


def test_import_repairs_bad_speaker_and_emotion():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"Hello there," said the guard.'])
    segs = dio.segment_chapter(sm, ch_id)
    labels = {"chapter_id": ch_id,
              "labels": [{"i": s["index"], "speaker": "Gandalf", "emotion": "bored"}
                         for s in segs]}
    dio.import_labels(sm, ch_id, labels)
    lines = sm.get_lines_for_chapter(ch_id)
    # out-of-roster dialogue speaker -> Unknown; bad emotion -> neutral.
    # (segmenter stores dialogue text WITHOUT surrounding quote marks.)
    dlg = [ln for ln in lines if ln["text"].startswith("Hello there")]
    assert dlg and dlg[0]["speaker"] == "Unknown", \
        f"dialogue should repair to Unknown, got {[ln['speaker'] for ln in lines]}"
    assert all(ln["emotion"] == "neutral" for ln in lines)
    print("  PASS test_import_repairs_bad_speaker_and_emotion")


def test_import_clobber_guard():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent."])
    dio.import_labels(sm, ch_id, _all_labels(sm, ch_id))      # -> diarized
    sm.mark_chapter_status(ch_id, "complete")
    try:
        dio.import_labels(sm, ch_id, _all_labels(sm, ch_id))  # no force
        assert False, "expected clobber rejection past diarized"
    except dio.ImportRejected:
        pass
    # force overrides
    n = dio.import_labels(sm, ch_id, _all_labels(sm, ch_id), force=True)
    assert n > 0 and sm.get_chapter_by_id(ch_id)["status"] == "diarized"
    print("  PASS test_import_clobber_guard")


TESTS = [
    test_segment_chapter_global_indices,
    test_build_export_payload,
    test_build_export_unknown_chapter_raises,
    test_system_prompt_text_has_roster_and_schema,
    test_import_round_trip_sets_diarized,
    test_import_enforcement_parity_with_llm,
    test_import_stale_count_mismatch_rejected,
    test_import_index_gap_rejected,
    test_import_repairs_bad_speaker_and_emotion,
    test_import_clobber_guard,
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
