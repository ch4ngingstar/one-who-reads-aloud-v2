"""
Test suite for Module 2: state_manager.py
Run: python tests/test_state_manager.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager


# ── Minimal ParsedBook fixture ────────────────────────────────────────────────

def _make_parsed_book(n_chapters=3, chunks_per_chapter=2):
    return {
        "source_epub": "shadow_slave.epub",
        "total_chapters": n_chapters,
        "chapters": [
            {
                "chapter_index": i,
                "title": f"Chapter {i + 1}: Test",
                "chunks": [
                    {"chunk_index": j, "text": f"Chunk {j} of chapter {i}.", "word_count": 6}
                    for j in range(chunks_per_chapter)
                ],
            }
            for i in range(n_chapters)
        ],
    }


def _tmp_db():
    """Return a StateManager backed by a fresh in-memory-equivalent temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_seed_project_creates_rows():
    sm = _tmp_db()
    book = _make_parsed_book(n_chapters=3, chunks_per_chapter=2)
    project_id = sm.seed_project(book)

    assert project_id > 0, "seed_project must return a positive project_id"

    project = sm.get_project("shadow_slave")
    assert project is not None
    assert project["total_chapters"] == 3

    chapters = sm.get_all_chapters(project_id)
    assert len(chapters) == 3
    assert chapters[0]["status"] == "pending"
    assert chapters[0]["total_chunks"] == 2

    chunks = sm.get_chunks_for_chapter(chapters[0]["id"])
    assert len(chunks) == 2
    assert chunks[0]["chunk_index"] == 0
    assert "Chunk 0" in chunks[0]["text"]

    print("  PASS test_seed_project_creates_rows")


def test_seed_idempotent():
    sm = _tmp_db()
    book = _make_parsed_book()
    id1 = sm.seed_project(book)
    id2 = sm.seed_project(book)  # second call should not duplicate
    assert id1 == id2

    chapters = sm.get_all_chapters(id1)
    assert len(chapters) == 3, f"Expected 3 chapters, got {len(chapters)}"
    print("  PASS test_seed_idempotent")


def test_chapter_status_lifecycle():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    chapters = sm.get_all_chapters(project_id)
    ch_id = chapters[0]["id"]

    sm.mark_chapter_status(ch_id, "diarized")
    refreshed = sm.get_all_chapters(project_id)[0]
    assert refreshed["status"] == "diarized"

    sm.mark_chapter_status(ch_id, "complete", audio_path="/output/ch1.mp3")
    refreshed = sm.get_all_chapters(project_id)[0]
    assert refreshed["status"] == "complete"
    assert refreshed["output_audio_path"] == "/output/ch1.mp3"

    print("  PASS test_chapter_status_lifecycle")


def test_invalid_chapter_status_raises():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]
    try:
        sm.mark_chapter_status(ch_id, "invalid_status")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("  PASS test_invalid_chapter_status_raises")


def test_save_and_retrieve_diarized_lines():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]

    lines = [
        {"line_index": 0, "speaker": "Narrator", "text": "The air was still.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "What is this place?", "emotion": "confused"},
        {"line_index": 2, "speaker": "Nephis",   "text": "Stay close.", "emotion": "whispers"},
    ]
    sm.save_diarized_lines(ch_id, lines)

    chapter = sm.get_all_chapters(project_id)[0]
    assert chapter["status"] == "diarized"
    assert chapter["total_lines"] == 3

    pending = sm.get_pending_tts_lines(ch_id)
    assert len(pending) == 3
    assert pending[0]["speaker"] == "Narrator"
    assert pending[2]["emotion"] == "whispers"

    print("  PASS test_save_and_retrieve_diarized_lines")


def test_save_diarized_replaces_existing():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]

    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "First pass.", "emotion": "neutral"},
    ])
    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "Second pass.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny", "text": "Replaced.", "emotion": "neutral"},
    ])
    pending = sm.get_pending_tts_lines(ch_id)
    assert len(pending) == 2
    assert pending[0]["text"] == "Second pass."
    print("  PASS test_save_diarized_replaces_existing")


def test_mark_line_tts_done():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]
    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "Test.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "Hello.", "emotion": "neutral"},
    ])

    pending = sm.get_pending_tts_lines(ch_id)
    sm.mark_line_tts_done(pending[0]["id"], "/audio/ch0/line_0000.wav")

    still_pending = sm.get_pending_tts_lines(ch_id)
    assert len(still_pending) == 1, "One line should still be pending"
    assert still_pending[0]["speaker"] == "Sunny"

    all_lines = sm.get_lines_for_chapter(ch_id)
    done_line = next(l for l in all_lines if l["line_index"] == 0)
    assert done_line["status"] == "tts_done"
    assert done_line["audio_path"] == "/audio/ch0/line_0000.wav"

    print("  PASS test_mark_line_tts_done")


def test_mark_line_failed():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]
    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "Fail me.", "emotion": "neutral"},
    ])
    line_id = sm.get_pending_tts_lines(ch_id)[0]["id"]
    sm.mark_line_failed(line_id, "CUDA OOM")

    progress = sm.get_line_progress(ch_id)
    assert progress["failed"] == 1
    assert progress["pending"] == 0
    print("  PASS test_mark_line_failed")


def test_voice_map_upsert():
    sm = _tmp_db()
    sm.set_voice("Sunny",  "/voices/sunny.wav")
    sm.set_voice("Nephis", "/voices/nephis.wav")
    vm = sm.get_voice_map()
    assert vm["Sunny"]["path"]  == "/voices/sunny.wav"
    assert vm["Nephis"]["path"] == "/voices/nephis.wav"

    # upsert changes path
    sm.set_voice("Sunny", "/voices/sunny_v2.wav")
    assert sm.get_voice_map()["Sunny"]["path"] == "/voices/sunny_v2.wav"
    assert len(sm.get_all_voices()) == 2

    print("  PASS test_voice_map_upsert")


def test_get_progress():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=4))
    chapters = sm.get_all_chapters(project_id)

    sm.mark_chapter_status(chapters[0]["id"], "complete")
    sm.mark_chapter_status(chapters[1]["id"], "diarized")
    sm.mark_chapter_status(chapters[2]["id"], "error", error_message="timeout")

    progress = sm.get_progress(project_id)
    assert progress["total"]    == 4
    assert progress["complete"] == 1
    assert progress["diarized"] == 1
    assert progress["error"]    == 1
    assert progress["pending"]  == 1
    assert progress["pct_complete"] == 25.0

    print("  PASS test_get_progress")


def test_get_chapters_by_status():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=3))
    chapters = sm.get_all_chapters(project_id)
    sm.mark_chapter_status(chapters[0]["id"], "diarized")

    pending  = sm.get_chapters_by_status(project_id, "pending")
    diarized = sm.get_chapters_by_status(project_id, "diarized")
    assert len(pending)  == 2
    assert len(diarized) == 1
    print("  PASS test_get_chapters_by_status")


def test_delete_voice():
    sm = _tmp_db()
    sm.set_voice("Sunny",  "/voices/sunny.wav")
    sm.set_voice("Nephis", "/voices/nephis.wav")

    found = sm.delete_voice("Sunny")
    assert found is True, "delete_voice should return True when speaker exists"

    vm = sm.get_voice_map()
    assert "Sunny"  not in vm
    assert "Nephis" in vm

    assert sm.delete_voice("Sunny") is False, "second delete should return False"
    print("  PASS test_delete_voice")


def test_mark_chapter_status_stores_file_size():
    sm = _tmp_db()
    project_id = sm.seed_project(_make_parsed_book(n_chapters=1))
    ch_id = sm.get_all_chapters(project_id)[0]["id"]

    sm.mark_chapter_status(ch_id, "complete",
                           audio_path="/output/ch_0001.mp3",
                           file_size_bytes=26_214_400)

    chapter = sm.get_all_chapters(project_id)[0]
    assert chapter["status"] == "complete"
    assert chapter["output_file_size_bytes"] == 26_214_400
    print("  PASS test_mark_chapter_status_stores_file_size")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_seed_project_creates_rows,
    test_seed_idempotent,
    test_chapter_status_lifecycle,
    test_invalid_chapter_status_raises,
    test_save_and_retrieve_diarized_lines,
    test_save_diarized_replaces_existing,
    test_mark_line_tts_done,
    test_mark_line_failed,
    test_voice_map_upsert,
    test_get_progress,
    test_get_chapters_by_status,
    test_delete_voice,
    test_mark_chapter_status_stores_file_size,
]

if __name__ == "__main__":
    print("Running Module 2 tests...\n")
    passed, failed = 0, 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
