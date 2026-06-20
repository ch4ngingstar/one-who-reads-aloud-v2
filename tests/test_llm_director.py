"""
Test suite for Module 3: llm_director.py (label-only two-pass) + segmenter.py
Run: python tests/test_llm_director.py

No GPU / no model required — _call_llm is monkeypatched in all tests.
"""

import sys
import json
import re
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from segmenter import segment_chunk
from llm_director import (
    LLMDirector, _parse_labels, _extract_json_block, _build_system_prompt,
    _is_narrator_misattribution, EMOTION_VOCAB, DEFAULT_SPEAKERS, SYSTEM_SPEAKER,
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
    director = LLMDirector(Path("fake_model.gguf"), sm, speakers=DEFAULT_SPEAKERS)
    director._llm      = object()   # truthy sentinel — bypasses "not loaded" check
    director._call_llm = mock_fn
    return director


def _labels_json(*labels):
    """Build a labels response from (i, speaker, emotion) tuples."""
    return json.dumps({"labels": [
        {"i": i, "speaker": s, "emotion": e} for i, s, e in labels
    ]})


def _words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


# ── Segmenter unit tests ──────────────────────────────────────────────────────

def test_segment_straight_quotes():
    segs = segment_chunk('Sunny stared at the runes. "What does it mean?" he asked quietly.')
    assert [s["kind"] for s in segs] == ["prose", "dialogue", "prose"]
    assert segs[0]["text"] == "Sunny stared at the runes."
    assert segs[1]["text"] == "What does it mean?"        # quotes stripped
    assert segs[2]["text"] == "he asked quietly."
    assert [s["index"] for s in segs] == [0, 1, 2]
    print("  PASS test_segment_straight_quotes")


def test_segment_curly_quotes():
    segs = segment_chunk("“Power,” she said. “Limitless power.”")
    assert [s["kind"] for s in segs] == ["dialogue", "prose", "dialogue"]
    assert segs[0]["text"] == "Power,"
    assert segs[2]["text"] == "Limitless power."
    print("  PASS test_segment_curly_quotes")


def test_segment_wrong_handed_curly_open_straight_close():
    # Real corruption seen in ch_1842/ch_244: dialogue OPENS with the right-curly
    # quote (U+201D) and CLOSES with a straight quote. Must still be dialogue, not
    # narrated as prose in the Narrator voice.
    segs = segment_chunk('”I see. That Memory is serving my husband well."')
    assert [s["kind"] for s in segs] == ["dialogue"]
    assert segs[0]["text"] == "I see. That Memory is serving my husband well."
    print("  PASS test_segment_wrong_handed_curly_open_straight_close")


def test_segment_wrong_handed_curly_both_right():
    # Both delimiters are the right-curly quote (U+201D ... U+201D).
    segs = segment_chunk('”The realm boundary is close. How long will it take?”')
    assert [s["kind"] for s in segs] == ["dialogue"]
    assert segs[0]["text"] == "The realm boundary is close. How long will it take?"
    print("  PASS test_segment_wrong_handed_curly_both_right")


def test_segment_wrong_handed_with_prose_tail():
    # Wrong-handed opener with an attribution tail still splits dialogue + prose.
    segs = segment_chunk('”Stop right there!” the guard shouted.')
    assert [s["kind"] for s in segs] == ["dialogue", "prose"]
    assert segs[0]["text"] == "Stop right there!"
    assert segs[1]["text"] == "the guard shouted."
    print("  PASS test_segment_wrong_handed_with_prose_tail")


def test_segment_apostrophes_not_split():
    segs = segment_chunk("It wasn't Sunny's fault, and he didn't care.")
    assert len(segs) == 1 and segs[0]["kind"] == "prose"
    print("  PASS test_segment_apostrophes_not_split")


def test_segment_thought_wrapped_paragraph():
    segs = segment_chunk("'That went better than expected.'")
    assert len(segs) == 1
    assert segs[0]["kind"] == "thought"
    assert segs[0]["text"] == "That went better than expected."   # quotes stripped
    print("  PASS test_segment_thought_wrapped_paragraph")


def test_segment_thought_with_contractions_stays_one_span():
    segs = segment_chunk("'We are running low on coffee, indeed. I'll have to go, won't I?'")
    assert len(segs) == 1 and segs[0]["kind"] == "thought"
    assert "I'll have to go, won't I?" in segs[0]["text"]
    print("  PASS test_segment_thought_with_contractions_stays_one_span")


def test_segment_inline_thought_in_prose():
    segs = segment_chunk("Sunny was panicking on the inside. 'What the hell?! No way.' He kept smiling.")
    assert [s["kind"] for s in segs] == ["prose", "thought", "prose"]
    assert segs[1]["text"] == "What the hell?! No way."
    print("  PASS test_segment_inline_thought_in_prose")


def test_segment_possessives_do_not_become_thoughts():
    segs = segment_chunk("The guards' weapons gleamed in Sunny's hand near the soldiers' camp.")
    assert len(segs) == 1 and segs[0]["kind"] == "prose"
    print("  PASS test_segment_possessives_do_not_become_thoughts")


def test_segment_curly_single_thought():
    segs = segment_chunk("‘One serving of pancakes coming right up...’")
    assert len(segs) == 1 and segs[0]["kind"] == "thought"
    print("  PASS test_segment_curly_single_thought")


def test_segment_system_paragraph_trailing_period():
    segs = segment_chunk("[Your shadow grows stronger.].")
    assert len(segs) == 1 and segs[0]["kind"] == "system"
    assert segs[0]["text"] == "[Your shadow grows stronger.]"
    print("  PASS test_segment_system_paragraph_trailing_period")


def test_segment_unbalanced_quote_falls_back_to_prose():
    text = 'He opened his mouth. "This quote never closes... and the paragraph ends.'
    segs = segment_chunk(text)
    assert len(segs) == 1
    assert segs[0]["kind"] == "prose"
    assert segs[0]["text"] == text
    print("  PASS test_segment_unbalanced_quote_falls_back_to_prose")


def test_segment_system_paragraph():
    segs = segment_chunk("[You have slain a Great Demon.]")
    assert len(segs) == 1
    assert segs[0]["kind"] == "system"
    assert segs[0]["text"] == "[You have slain a Great Demon.]"   # brackets kept
    print("  PASS test_segment_system_paragraph")


def test_segment_multiple_brackets_one_paragraph():
    segs = segment_chunk("[Your shadow grows stronger.] [You have gained a soul shard.]")
    assert [s["kind"] for s in segs] == ["system", "system"]
    print("  PASS test_segment_multiple_brackets_one_paragraph")


def test_segment_inline_bracket_stays_prose():
    segs = segment_chunk("He gripped the [Silver Bell] tightly and ran.")
    assert len(segs) == 1 and segs[0]["kind"] == "prose"
    assert "[Silver Bell]" in segs[0]["text"]
    print("  PASS test_segment_inline_bracket_stays_prose")


def test_segment_multi_paragraph_order_and_indices():
    text = ('Sunny walked forward.\n\n'
            '"Stop right there!"\n\n'
            '[Warning: hostile entity detected.]\n\n'
            'The shadows deepened.')
    segs = segment_chunk(text)
    assert [s["kind"] for s in segs] == ["prose", "dialogue", "system", "prose"]
    assert [s["index"] for s in segs] == [0, 1, 2, 3]
    print("  PASS test_segment_multi_paragraph_order_and_indices")


def test_segment_empty_input():
    assert segment_chunk("") == []
    assert segment_chunk("   \n\n   ") == []
    print("  PASS test_segment_empty_input")


def test_segment_word_coverage_invariant():
    """Every source word must land in exactly one segment (none lost, none duplicated)."""
    text = ('Sunny stared at the gates. "Who goes there?" a guard demanded. '
            '"A traveler," Sunny replied calmly.\n\n'
            '[You have entered the Crimson Spire.]\n\n'
            'The doors swung open with a heavy groan.')
    segs = segment_chunk(text)
    src_words = _words(text)
    out_words = _words(" ".join(s["text"] for s in segs))
    assert sorted(src_words) == sorted(out_words), "segment words != source words"
    print("  PASS test_segment_word_coverage_invariant")


# ── Label parsing tests ───────────────────────────────────────────────────────

def test_extract_json_block_strips_markdown():
    raw = '```json\n{"labels": []}\n```'
    assert _extract_json_block(raw) == '{"labels": []}'
    print("  PASS test_extract_json_block_strips_markdown")


def test_parse_labels_happy_path():
    raw = _labels_json((0, "Narrator", "neutral"), (1, "Sunny", "confused"))
    labels = _parse_labels(raw, n_segments=2)
    assert labels[0] == ("Narrator", "neutral")
    assert labels[1] == ("Sunny", "confused")
    print("  PASS test_parse_labels_happy_path")


def test_parse_labels_missing_index_raises():
    raw = _labels_json((0, "Narrator", "neutral"))
    try:
        _parse_labels(raw, n_segments=2)
        assert False, "Should have raised ValueError for missing index 1"
    except ValueError:
        pass
    print("  PASS test_parse_labels_missing_index_raises")


def test_parse_labels_invalid_emotion_falls_back():
    raw = _labels_json((0, "Sunny", "mega_rage_invalid"))
    labels = _parse_labels(raw, n_segments=1)
    assert labels[0][1] == "neutral"
    print("  PASS test_parse_labels_invalid_emotion_falls_back")


def test_parse_labels_raises_on_no_json():
    try:
        _parse_labels("This is not JSON at all.", n_segments=1)
        assert False, "Should have raised"
    except (ValueError, json.JSONDecodeError):
        pass
    print("  PASS test_parse_labels_raises_on_no_json")


# ── Enforcement tests (via _merge_labels through _process_chunk) ─────────────

def test_prose_inner_monologue_first_person_kept():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Sunny", "confused")))
    lines = director._process_chunk("Why me? I never asked for any of this.", 0)
    assert lines[0]["speaker"] == "Sunny", "first-person prose labeled Sunny must be kept"
    print("  PASS test_prose_inner_monologue_first_person_kept")


def test_prose_third_person_sunny_flipped_to_narrator():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Sunny", "cold")))
    lines = director._process_chunk("Sunny walked into the room and sighed heavily.", 0)
    assert lines[0]["speaker"] == "Narrator", "third-person prose must flip to Narrator"
    print("  PASS test_prose_third_person_sunny_flipped_to_narrator")


def test_prose_other_speaker_flipped_to_narrator():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Nephis", "commanding")))
    lines = director._process_chunk("The fortress loomed over the valley below.", 0)
    assert lines[0]["speaker"] == "Narrator", "prose may only be Narrator (or guarded Sunny)"
    print("  PASS test_prose_other_speaker_flipped_to_narrator")


def test_prose_keeps_llm_emotion():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Narrator", "frightened")))
    lines = director._process_chunk("The abomination dragged itself out of the dark.", 0)
    assert lines[0]["speaker"] == "Narrator"
    assert lines[0]["emotion"] == "frightened", "narrator emotion from LLM must survive"
    print("  PASS test_prose_keeps_llm_emotion")


def test_system_segment_invalid_label_forced_to_nightmare_spell():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "NotARealCharacter", "cold")))
    lines = director._process_chunk("[You have slain a Great Demon.]", 0)
    assert lines[0]["speaker"] == SYSTEM_SPEAKER
    print("  PASS test_system_segment_invalid_label_forced_to_nightmare_spell")


def test_system_segment_telepathy_keeps_character_label():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Cassie", "neutral")))
    lines = director._process_chunk("[I don't sense anyone else. There is nobody there...]", 0)
    assert lines[0]["speaker"] == "Cassie", "bracketed telepathy keeps the sender's label"
    print("  PASS test_system_segment_telepathy_keeps_character_label")


def test_system_segment_narrator_override_allowed():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Narrator", "neutral")))
    lines = director._process_chunk("[1591/6000]", 0)
    assert lines[0]["speaker"] == "Narrator", "stat readouts may be Narrator"
    print("  PASS test_system_segment_narrator_override_allowed")


def test_thought_keeps_pov_character_label():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Rain", "confused")))
    lines = director._process_chunk("'She has been gone for almost a month now...'", 0)
    assert lines[0]["speaker"] == "Rain", "thought POV label must be trusted (no prose guard)"
    print("  PASS test_thought_keeps_pov_character_label")


def test_thought_impossible_label_repaired_to_sunny():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, SYSTEM_SPEAKER, "cold")))
    lines = director._process_chunk("'What a strange power...'", 0)
    assert lines[0]["speaker"] == "Sunny"
    print("  PASS test_thought_impossible_label_repaired_to_sunny")


def test_dialogue_narrator_label_becomes_unknown():
    sm = _tmp_sm()
    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Narrator", "neutral")))
    lines = director._process_chunk('"Who goes there?"', 0)
    assert lines[0]["speaker"] == "Unknown", "dialogue can never be spoken by Narrator"
    print("  PASS test_dialogue_narrator_label_becomes_unknown")


def test_misattribution_guard_semantics():
    assert _is_narrator_misattribution("Sunny", "Sunny walked forward slowly.")
    assert _is_narrator_misattribution("Sunny", "He sighed and opened his eyes.")
    assert _is_narrator_misattribution(
        "Sunny", "After a long while the young man known as Sunny yawned.")
    assert not _is_narrator_misattribution("Sunny", "I have to run. Now.")
    assert not _is_narrator_misattribution("Nephis", "My name is Nephis.")
    assert not _is_narrator_misattribution("Narrator", "Anything at all.")
    print("  PASS test_misattribution_guard_semantics")


# ── Integration tests (mocked _call_llm) ──────────────────────────────────────

def test_process_chapter_happy_path():
    sm = _tmp_sm()
    text = 'Sunny stared at the runes. "What does it mean?" he asked quietly.'
    _, ch_id = _seed_chapter(sm, [text])

    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Narrator", "neutral"), (1, "Sunny", "confused"), (2, "Narrator", "neutral")))
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 3
    chapter = sm.get_all_chapters(sm.get_project("test")["id"])[0]
    assert chapter["status"] == "diarized"
    assert chapter["total_lines"] == 3

    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["speaker"] == "Narrator"
    assert lines[1]["speaker"] == "Sunny"
    assert lines[1]["text"] == "What does it mean?"
    assert lines[1]["emotion"] == "confused"
    print("  PASS test_process_chapter_happy_path")


def test_process_chapter_multiple_chunks_offsets():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["Chunk one text here.", "Chunk two text here."])

    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: _labels_json(
        (0, "Narrator", "neutral")))
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 2
    lines = sm.get_lines_for_chapter(ch_id)
    assert [ln["line_index"] for ln in lines] == [0, 1]
    assert "Chunk one" in lines[0]["text"]
    assert "Chunk two" in lines[1]["text"]
    print("  PASS test_process_chapter_multiple_chunks_offsets")


def test_retry_on_bad_json_then_succeed():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The darkness stirred."])

    call_count = [0]

    def mock_fn(text, temperature=0.2):
        call_count[0] += 1
        if call_count[0] < 2:
            return "This is broken JSON {{{{"
        return _labels_json((0, "Narrator", "neutral"))

    director = _make_director(sm, mock_fn=mock_fn)
    n_lines = director.process_chapter(ch_id)
    assert n_lines == 1
    assert call_count[0] == 2, f"Expected 2 calls (1 fail + 1 success), got {call_count[0]}"
    print("  PASS test_retry_on_bad_json_then_succeed")


def test_fallback_on_total_failure_preserves_all_text():
    sm = _tmp_sm()
    text = ('The shadow consumed everything. "Run!" she screamed.\n\n'
            '[A Nightmare Creature approaches.]')
    _, ch_id = _seed_chapter(sm, [text])

    director = _make_director(sm, mock_fn=lambda t, temperature=0.2: "not json }")
    n_lines = director.process_chapter(ch_id)

    assert n_lines == 4, f"Expected 4 fallback segments, got {n_lines}"
    lines = sm.get_lines_for_chapter(ch_id)
    src_words = _words(text)
    out_words = _words(" ".join(ln["text"] for ln in lines))
    assert sorted(src_words) == sorted(out_words), "fallback must preserve every word"
    by_kind = {ln["text"]: ln["speaker"] for ln in lines}
    assert by_kind["Run!"] == "Unknown", "fallback dialogue -> Unknown"
    assert by_kind["[A Nightmare Creature approaches.]"] == SYSTEM_SPEAKER
    print("  PASS test_fallback_on_total_failure_preserves_all_text")


def test_qwen3_no_think_appended():
    sm = _tmp_sm()
    captured = []

    def mock_fn(text, temperature=0.2):
        captured.append(text)
        return _labels_json((0, "Narrator", "neutral"))

    director = _make_director(sm, mock_fn=mock_fn)
    director.model_path = Path("Qwen3-14B-Q4_K_M.gguf")
    director._process_chunk("The night was silent.", 0)
    assert captured[0].endswith("/no_think"), "Qwen3 models must get the /no_think switch"

    captured.clear()
    director.model_path = Path("qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf")
    director._process_chunk("The night was silent.", 0)
    assert "/no_think" not in captured[0], "Qwen2.5 must not see /no_think"
    print("  PASS test_qwen3_no_think_appended")


def test_system_prompt_contains_roster_and_emotions():
    prompt = _build_system_prompt(DEFAULT_SPEAKERS)
    assert "Narrator" in prompt and "Unknown" in prompt and SYSTEM_SPEAKER in prompt
    for spk in DEFAULT_SPEAKERS:
        assert spk in prompt
    for emo in EMOTION_VOCAB:
        assert emo in prompt
    print("  PASS test_system_prompt_contains_roster_and_emotions")


def test_context_manager_raises_without_model():
    sm = _tmp_sm()
    try:
        with LLMDirector("/nonexistent/model.gguf", sm) as d:
            pass
        assert False, "Should have raised"
    except (FileNotFoundError, RuntimeError):
        pass
    print("  PASS test_context_manager_raises_without_model")


def test_call_llm_raises_outside_context():
    sm = _tmp_sm()
    director = LLMDirector(Path("fake.gguf"), sm, speakers=[])
    try:
        director._call_llm("test text")
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        pass
    print("  PASS test_call_llm_raises_outside_context")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    # segmenter
    test_segment_straight_quotes,
    test_segment_curly_quotes,
    test_segment_apostrophes_not_split,
    test_segment_thought_wrapped_paragraph,
    test_segment_thought_with_contractions_stays_one_span,
    test_segment_inline_thought_in_prose,
    test_segment_possessives_do_not_become_thoughts,
    test_segment_curly_single_thought,
    test_segment_system_paragraph_trailing_period,
    test_segment_unbalanced_quote_falls_back_to_prose,
    test_segment_system_paragraph,
    test_segment_multiple_brackets_one_paragraph,
    test_segment_inline_bracket_stays_prose,
    test_segment_multi_paragraph_order_and_indices,
    test_segment_empty_input,
    test_segment_word_coverage_invariant,
    # label parsing
    test_extract_json_block_strips_markdown,
    test_parse_labels_happy_path,
    test_parse_labels_missing_index_raises,
    test_parse_labels_invalid_emotion_falls_back,
    test_parse_labels_raises_on_no_json,
    # enforcement
    test_prose_inner_monologue_first_person_kept,
    test_prose_third_person_sunny_flipped_to_narrator,
    test_prose_other_speaker_flipped_to_narrator,
    test_prose_keeps_llm_emotion,
    test_system_segment_invalid_label_forced_to_nightmare_spell,
    test_system_segment_telepathy_keeps_character_label,
    test_system_segment_narrator_override_allowed,
    test_thought_keeps_pov_character_label,
    test_thought_impossible_label_repaired_to_sunny,
    test_dialogue_narrator_label_becomes_unknown,
    test_misattribution_guard_semantics,
    # integration
    test_process_chapter_happy_path,
    test_process_chapter_multiple_chunks_offsets,
    test_retry_on_bad_json_then_succeed,
    test_fallback_on_total_failure_preserves_all_text,
    test_qwen3_no_think_appended,
    test_system_prompt_contains_roster_and_emotions,
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
