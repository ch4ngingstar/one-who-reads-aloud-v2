"""
Test suite for Module 3: llm_director.py
Run: python tests/test_llm_director.py

No GPU / no model required — _call_llm is monkeypatched in all tests.
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from llm_director import (
    LLMDirector, _parse_lines, _extract_json_block,
    EMOTION_VOCAB, DEFAULT_SPEAKERS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_chapter(sm, text_chunks):
    """Seed a one-chapter project and return (project_id, chapter_id)."""
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 0,
            "title": "Chapter 1",
            "chunks": [
                {"chunk_index": i, "text": t, "word_count": len(t.split())}
                for i, t in enumerate(text_chunks)
            ],
        }],
    }
    pid = sm.seed_project(book)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    return pid, ch_id


def _make_director(sm, mock_fn):
    """Create an LLMDirector with _call_llm replaced by mock_fn (no model loaded)."""
    director = LLMDirector.__new__(LLMDirector)
    director.model_path     = Path("fake_model.gguf")
    director.sm             = sm
    director.speakers       = DEFAULT_SPEAKERS
    director.cfg            = {
        "n_ctx": 4096, "n_batch": 512, "n_gpu_layers": -1,
        "verbose": False, "temperature": 0.1, "max_tokens": 4096,
        "retry_temp": 0.4, "max_retries": 3,
    }
    from llm_director import _build_system_prompt
    director._system_prompt = _build_system_prompt(DEFAULT_SPEAKERS)
    director._llm           = object()  # truthy sentinel — bypasses "not loaded" check
    director._call_llm      = mock_fn
    return director


# ── Parser unit tests ─────────────────────────────────────────────────────────

def test_extract_json_block_clean():
    raw = '{"lines": [{"line_index": 0, "speaker": "Narrator", "text": "hi", "emotion": "neutral"}]}'
    result = _extract_json_block(raw)
    assert result == raw
    print("  PASS test_extract_json_block_clean")


def test_extract_json_block_strips_markdown():
    raw = '```json\n{"lines": []}\n```'
    result = _extract_json_block(raw)
    assert result == '{"lines": []}'
    print("  PASS test_extract_json_block_strips_markdown")


def test_extract_json_block_embedded():
    raw = 'Sure! Here is the JSON:\n{"lines": [{"line_index": 0, "speaker": "Sunny", "text": "hi", "emotion": "neutral"}]}\nDone.'
    result = _extract_json_block(raw)
    parsed = json.loads(result)
    assert "lines" in parsed
    print("  PASS test_extract_json_block_embedded")


def test_parse_lines_happy_path():
    response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Narrator", "text": "The room was dark.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "What is this place?", "emotion": "confused"},
    ]})
    lines = _parse_lines(response, line_offset=0)
    assert len(lines) == 2
    assert lines[0]["speaker"] == "Narrator"
    assert lines[1]["emotion"] == "confused"
    assert lines[1]["line_index"] == 1
    print("  PASS test_parse_lines_happy_path")


def test_parse_lines_reindexes_with_offset():
    response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Narrator", "text": "Text A.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Nephis",   "text": "Text B.", "emotion": "cold"},
    ]})
    lines = _parse_lines(response, line_offset=10)
    assert lines[0]["line_index"] == 10
    assert lines[1]["line_index"] == 11
    print("  PASS test_parse_lines_reindexes_with_offset")


def test_parse_lines_corrects_invalid_emotion():
    response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Sunny", "text": "Hello.", "emotion": "very_angry_invalid"},
    ]})
    lines = _parse_lines(response, line_offset=0)
    assert lines[0]["emotion"] == "neutral", "Invalid emotion should fall back to neutral"
    print("  PASS test_parse_lines_corrects_invalid_emotion")


def test_parse_lines_skips_empty_text():
    response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Narrator", "text": "", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "Real line.", "emotion": "neutral"},
    ]})
    lines = _parse_lines(response, line_offset=0)
    assert len(lines) == 1
    assert lines[0]["text"] == "Real line."
    print("  PASS test_parse_lines_skips_empty_text")


def test_parse_lines_raises_on_missing_lines_key():
    response = json.dumps({"result": []})
    try:
        _parse_lines(response)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("  PASS test_parse_lines_raises_on_missing_lines_key")


def test_parse_lines_raises_on_no_json():
    try:
        _parse_lines("This is not JSON at all.")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("  PASS test_parse_lines_raises_on_no_json")


# ── Integration tests (mocked _call_llm) ──────────────────────────────────────

def test_process_chapter_happy_path():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["Sunny walked into the void."])

    mock_response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Narrator", "text": "Sunny walked into the void.", "emotion": "neutral"},
    ]})

    director = _make_director(sm, mock_fn=lambda text, temperature=0.1: mock_response)
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 1
    chapter = sm.get_all_chapters(sm.get_project("test")["id"])[0]
    assert chapter["status"] == "diarized"
    assert chapter["total_lines"] == 1

    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["speaker"] == "Narrator"
    assert lines[0]["text"] == "Sunny walked into the void."
    print("  PASS test_process_chapter_happy_path")


def test_process_chapter_multiple_chunks():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["Chunk one text.", "Chunk two text."])

    def mock_fn(text, temperature=0.1):
        return json.dumps({"lines": [
            {"line_index": 0, "speaker": "Narrator", "text": text, "emotion": "neutral"},
        ]})

    director = _make_director(sm, mock_fn=mock_fn)
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 2
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["line_index"] == 0
    assert lines[1]["line_index"] == 1
    assert "Chunk one" in lines[0]["text"]
    assert "Chunk two" in lines[1]["text"]
    print("  PASS test_process_chapter_multiple_chunks")


def test_retry_on_bad_json_then_succeed():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The darkness stirred."])

    call_count = [0]
    good_response = json.dumps({"lines": [
        {"line_index": 0, "speaker": "Narrator", "text": "The darkness stirred.", "emotion": "neutral"},
    ]})

    def mock_fn(text, temperature=0.1):
        call_count[0] += 1
        if call_count[0] < 2:
            return "This is broken JSON {{{{"
        return good_response

    director = _make_director(sm, mock_fn=mock_fn)
    n_lines = director.process_chapter(ch_id)
    assert n_lines == 1
    assert call_count[0] == 2, f"Expected 2 calls (1 fail + 1 success), got {call_count[0]}"
    print("  PASS test_retry_on_bad_json_then_succeed")


def test_fallback_on_total_failure():
    sm = _tmp_sm()
    original_text = "The shadow consumed everything in its path."
    _, ch_id = _seed_chapter(sm, [original_text])

    director = _make_director(sm, mock_fn=lambda text, temperature=0.1: "not json }")
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 1, "Fallback must produce exactly 1 Narrator line"
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["speaker"] == "Narrator"
    assert lines[0]["text"] == original_text, "Fallback must preserve original text verbatim"
    print("  PASS test_fallback_on_total_failure")


def test_context_manager_raises_without_model():
    """Verify __enter__ raises FileNotFoundError when model file is missing."""
    sm = _tmp_sm()
    try:
        with LLMDirector("/nonexistent/model.gguf", sm) as d:
            pass
        assert False, "Should have raised"
    except (FileNotFoundError, RuntimeError):
        pass
    print("  PASS test_context_manager_raises_without_model")


def test_call_llm_raises_outside_context():
    """Verify _call_llm raises RuntimeError if called without entering context."""
    sm = _tmp_sm()
    director = LLMDirector.__new__(LLMDirector)
    director.model_path     = Path("fake.gguf")
    director.sm             = sm
    director.speakers       = []
    director.cfg            = {"max_retries": 1, "temperature": 0.1,
                               "retry_temp": 0.4, "max_tokens": 512,
                               "n_ctx": 512, "n_batch": 64,
                               "n_gpu_layers": 0, "verbose": False}
    from llm_director import _build_system_prompt
    director._system_prompt = _build_system_prompt([])
    director._llm           = None   # not loaded

    try:
        director._call_llm("test text")
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass
    print("  PASS test_call_llm_raises_outside_context")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_extract_json_block_clean,
    test_extract_json_block_strips_markdown,
    test_extract_json_block_embedded,
    test_parse_lines_happy_path,
    test_parse_lines_reindexes_with_offset,
    test_parse_lines_corrects_invalid_emotion,
    test_parse_lines_skips_empty_text,
    test_parse_lines_raises_on_missing_lines_key,
    test_parse_lines_raises_on_no_json,
    test_process_chapter_happy_path,
    test_process_chapter_multiple_chunks,
    test_retry_on_bad_json_then_succeed,
    test_fallback_on_total_failure,
    test_context_manager_raises_without_model,
    test_call_llm_raises_outside_context,
]

if __name__ == "__main__":
    print("Running Module 3 tests...\n")
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
