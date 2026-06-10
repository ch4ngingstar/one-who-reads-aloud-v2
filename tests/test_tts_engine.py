"""
Test suite for Module 4: tts_engine.py (IndexTTS2 backend)
Run: python tests/test_tts_engine.py

No GPU / no IndexTTS2 model required — `_synthesize` is monkeypatched in all
integration tests, and the engine is never entered as a context manager (so no
model is loaded).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from tts_engine import (
    TTSEngine,
    INDEXTTS2_EMOTION_VECTORS,
    _wav_silence,
    _normalize_text,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_synth(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
    """Drop-in replacement for TTSEngine._synthesize that returns silent WAV."""
    return _wav_silence()


def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _tmp_wav() -> Path:
    """Write a tiny valid WAV file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(_wav_silence(duration_ms=200))
    tmp.close()
    return Path(tmp.name)


def _seed_diarized_chapter(sm, lines):
    """Seed a project, diarize chapter 0 with given lines. Returns chapter_id."""
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 0,
            "title": "Chapter 1",
            "chunks": [{"chunk_index": 0, "text": "dummy", "word_count": 1}],
        }],
    }
    pid = sm.seed_project(book)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    sm.save_diarized_lines(ch_id, lines)
    return ch_id


def _make_engine(sm, output_dir, mock_synth=None):
    """Create a TTSEngine without loading a model; optionally mock _synthesize."""
    engine = TTSEngine(state_manager=sm, output_dir=output_dir)
    if mock_synth is not None:
        engine._synthesize = mock_synth
    return engine


# ── Emotion vector tests ──────────────────────────────────────────────────────

def test_emotion_vocab_all_mapped():
    # Every emotion the engine knows must map to an 8-dim vector + alpha.
    for emotion, (vec, alpha) in INDEXTTS2_EMOTION_VECTORS.items():
        assert len(vec) == 8, f"{emotion}: vector must be 8-dim, got {len(vec)}"
        assert 0.0 <= alpha <= 1.0, f"{emotion}: alpha out of range: {alpha}"
        assert all(0.0 <= v <= 1.0 for v in vec), f"{emotion}: vector value out of range"
    print("  PASS test_emotion_vocab_all_mapped")


def test_resolve_emotion_neutral_is_pure_timbre():
    vec, alpha = TTSEngine._resolve_emotion("neutral")
    assert vec is None and alpha == 0.0, f"neutral must be pure timbre, got {(vec, alpha)}"
    print("  PASS test_resolve_emotion_neutral_is_pure_timbre")


def test_resolve_emotion_unknown_is_pure_timbre():
    vec, alpha = TTSEngine._resolve_emotion("not_a_real_emotion")
    assert vec is None and alpha == 0.0, f"unknown must be pure timbre, got {(vec, alpha)}"
    print("  PASS test_resolve_emotion_unknown_is_pure_timbre")


def test_resolve_emotion_angry_has_anger_component():
    vec, alpha = TTSEngine._resolve_emotion("angry")
    assert vec is not None, "angry must produce a vector"
    # index 1 = angry in [happy, angry, sad, afraid, disgust, melancholic, surprised, calm]
    assert vec[1] > 0.5, f"angry component should dominate, got {vec}"
    assert alpha > 0.0, "angry must have non-zero intensity"
    print("  PASS test_resolve_emotion_angry_has_anger_component")


def test_synthesize_receives_emotion_vector():
    """Emotional lines pass an emo_vector; neutral lines pass None."""
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))
    sm.set_voice("Sunny", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "All was still.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "Get back!",      "emotion": "angry"},
    ])

    captured = []
    def capture(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        captured.append({"emo_vector": emo_vector, "emo_alpha": emo_alpha})
        return _wav_silence()

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=capture)
        engine.process_chapter(ch_id)

    # Line 0 (neutral) → no emotion vector
    assert captured[0]["emo_vector"] is None, f"neutral should pass None, got {captured[0]}"
    # Line 1 (angry) → emotion vector with anger
    assert captured[1]["emo_vector"] is not None, "angry should pass a vector"
    assert captured[1]["emo_vector"][1] > 0.5, "angry vector should carry anger"
    assert captured[1]["emo_alpha"] > 0.0, "angry should have intensity"

    ref_wav.unlink(missing_ok=True)
    print("  PASS test_synthesize_receives_emotion_vector")


def test_emo_alpha_scale_applied():
    """The global emo_alpha_scale config multiplies per-emotion alpha."""
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Sunny", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Sunny", "text": "No!", "emotion": "angry"},
    ])

    captured = []
    def capture(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        captured.append(emo_alpha)
        return _wav_silence()

    base_alpha = INDEXTTS2_EMOTION_VECTORS["angry"][1]
    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=capture)
        engine.cfg["emo_alpha_scale"] = 0.5
        engine.process_chapter(ch_id)

    assert abs(captured[0] - base_alpha * 0.5) < 1e-6, (
        f"Expected scaled alpha {base_alpha * 0.5}, got {captured[0]}"
    )
    ref_wav.unlink(missing_ok=True)
    print("  PASS test_emo_alpha_scale_applied")


# ── Voice resolution tests ────────────────────────────────────────────────────

def test_resolve_ref_audio_primary():
    voice_map = {"Sunny": "/voices/sunny.wav", "Narrator": "/voices/narrator.wav"}
    result = TTSEngine._resolve_ref_audio("Sunny", "neutral", voice_map)
    assert result == ("/voices/sunny.wav", ""), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_primary")


def test_resolve_ref_audio_emotion_override():
    # Legacy emotion-specific clips still resolve if present.
    voice_map = {
        "Sunny":          "/voices/sunny.wav",
        "Sunny_whispers": "/voices/sunny_quiet.wav",
    }
    result = TTSEngine._resolve_ref_audio("Sunny", "whispers", voice_map)
    assert result == ("/voices/sunny_quiet.wav", ""), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_emotion_override")


def test_resolve_ref_audio_falls_back_to_primary():
    voice_map = {"Sunny": "/voices/sunny.wav"}
    result = TTSEngine._resolve_ref_audio("Sunny", "angry", voice_map)
    assert result == ("/voices/sunny.wav", ""), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_falls_back_to_primary")


def test_resolve_ref_audio_missing_returns_none():
    result = TTSEngine._resolve_ref_audio("UnknownChar", "neutral", {})
    assert result is None
    print("  PASS test_resolve_ref_audio_missing_returns_none")


def test_resolve_ref_audio_falls_back_to_default():
    voice_map = {"_default": "/voices/default.wav"}
    result = TTSEngine._resolve_ref_audio("UnknownChar", "neutral", voice_map)
    assert result == ("/voices/default.wav", ""), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_falls_back_to_default")


def test_resolve_ref_audio_dict_entry():
    # voice_map values are {"path":..,"ref_text":..} from StateManager.
    voice_map = {"Sunny": {"path": "/voices/sunny.wav", "ref_text": "Hello."}}
    result = TTSEngine._resolve_ref_audio("Sunny", "neutral", voice_map)
    assert result == ("/voices/sunny.wav", "Hello."), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_dict_entry")


def test_wav_silence_is_valid_wav():
    wav = _wav_silence(duration_ms=100)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) > 44
    print("  PASS test_wav_silence_is_valid_wav")


def test_synthesize_requires_loaded_model():
    """Calling the real _synthesize without a loaded model must error clearly."""
    sm = _tmp_sm()
    engine = TTSEngine(state_manager=sm, output_dir="/tmp")
    try:
        engine._synthesize("hi", "/voices/x.wav")
        assert False, "Expected RuntimeError when model is not loaded"
    except RuntimeError as e:
        assert "not loaded" in str(e).lower()
    print("  PASS test_synthesize_requires_loaded_model")


def test_load_model_requires_model_dir():
    """__enter__ / _load_model must fail clearly without a model_dir."""
    sm = _tmp_sm()
    engine = TTSEngine(state_manager=sm, output_dir="/tmp")  # no model_dir
    try:
        engine._load_model()
        assert False, "Expected ValueError without model_dir"
    except ValueError as e:
        assert "model_dir" in str(e)
    print("  PASS test_load_model_requires_model_dir")


def test_back_compat_fish_speech_dir_kwarg():
    """Old callers passing fish_speech_dir must still construct without error."""
    sm = _tmp_sm()
    engine = TTSEngine(sm, "/tmp", fish_speech_dir="some/checkpoints",
                       server_url="http://x", managed_server=True)
    assert str(engine.model_dir) == str(Path("some/checkpoints"))
    print("  PASS test_back_compat_fish_speech_dir_kwarg")


# ── Integration tests (mocked synth) ──────────────────────────────────────────

def test_process_chapter_generates_wav_files():
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))
    sm.set_voice("Sunny", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "The void yawned open.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "I am not afraid.",      "emotion": "cold"},
    ])

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=_mock_synth)
        n = engine.process_chapter(ch_id)

        assert n == 2
        wav0 = Path(out_dir) / f"ch_{ch_id:04d}" / "line_0000.wav"
        wav1 = Path(out_dir) / f"ch_{ch_id:04d}" / "line_0001.wav"
        assert wav0.exists(), f"Missing {wav0}"
        assert wav1.exists(), f"Missing {wav1}"

    chapter = sm.get_all_chapters(sm.get_project("test")["id"])[0]
    assert chapter["status"] == "tts_done"

    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["status"] == "tts_done"
    assert lines[1]["status"] == "tts_done"
    assert "line_0000.wav" in lines[0]["audio_path"]

    ref_wav.unlink(missing_ok=True)
    print("  PASS test_process_chapter_generates_wav_files")


def test_process_chapter_skips_missing_voice():
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "Scene begins.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "No voice set.", "emotion": "neutral"},
    ])

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=_mock_synth)
        n = engine.process_chapter(ch_id)

    assert n == 1, f"Only 1 line should succeed, got {n}"
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["status"] == "tts_done"
    assert lines[1]["status"] == "failed"
    assert "No reference audio" in lines[1]["error_message"]

    ref_wav.unlink(missing_ok=True)
    print("  PASS test_process_chapter_skips_missing_voice")


def test_process_chapter_retries_on_failure():
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "Test.", "emotion": "neutral"},
    ])

    call_count = [0]
    def flaky_synth(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        call_count[0] += 1
        if call_count[0] < 2:
            raise RuntimeError("Generation glitch")
        return _wav_silence()

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=flaky_synth)
        n = engine.process_chapter(ch_id)

    assert n == 1
    assert call_count[0] == 2, f"Expected 2 calls (1 fail + 1 retry), got {call_count[0]}"
    ref_wav.unlink(missing_ok=True)
    print("  PASS test_process_chapter_retries_on_failure")


def test_process_chapter_marks_failed_after_all_retries():
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "Always fails.", "emotion": "neutral"},
    ])

    def always_fail(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        raise RuntimeError("VRAM OOM")

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=always_fail)
        n = engine.process_chapter(ch_id)

    assert n == 0
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["status"] == "failed"
    assert "VRAM OOM" in lines[0]["error_message"]
    ref_wav.unlink(missing_ok=True)
    print("  PASS test_process_chapter_marks_failed_after_all_retries")


def test_process_chapter_empty_no_crash():
    """Chapter with no pending lines should complete gracefully."""
    sm = _tmp_sm()
    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "Text.", "emotion": "neutral"},
    ])
    lines = sm.get_pending_tts_lines(ch_id)
    sm.mark_line_tts_done(lines[0]["id"], "/fake/path.wav")

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir)
        n = engine.process_chapter(ch_id)

    assert n == 0
    print("  PASS test_process_chapter_empty_no_crash")


def test_process_chapter_uses_default_fallback():
    """Lines with no registered speaker voice should synthesize using '_default'."""
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("_default", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Sunny", "text": "Uses default.", "emotion": "neutral"},
    ])

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=_mock_synth)
        n = engine.process_chapter(ch_id)

    assert n == 1, f"Expected 1 success via _default fallback, got {n}"
    lines = sm.get_lines_for_chapter(ch_id)
    assert lines[0]["status"] == "tts_done"

    ref_wav.unlink(missing_ok=True)
    print("  PASS test_process_chapter_uses_default_fallback")


def test_emotion_override_voice_used():
    """When Sunny_whispers is in voice_map, it must be used for whisper lines."""
    sm = _tmp_sm()
    ref_default = _tmp_wav()
    ref_quiet   = _tmp_wav()
    sm.set_voice("Sunny",          str(ref_default))
    sm.set_voice("Sunny_whispers", str(ref_quiet))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Sunny", "text": "I know.", "emotion": "whispers"},
    ])

    used_refs = []
    def capture_synth(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        used_refs.append(ref)
        return _wav_silence()

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=capture_synth)
        engine.process_chapter(ch_id)

    assert used_refs[0] == str(ref_quiet), f"Expected whisper ref, got: {used_refs[0]}"
    ref_default.unlink(missing_ok=True)
    ref_quiet.unlink(missing_ok=True)
    print("  PASS test_emotion_override_voice_used")


# ── _split_long_line tests ────────────────────────────────────────────────────

def test_split_short_line_unchanged():
    result = TTSEngine._split_long_line("Short line.", 400)
    assert result == ["Short line."], f"Got: {result}"
    print("  PASS test_split_short_line_unchanged")


def test_split_at_sentence_boundary():
    text = "First sentence. " + "A" * 50 + ". " + "B" * 50 + "."
    result = TTSEngine._split_long_line(text, 60)
    assert len(result) > 1, "Expected at least 2 chunks"
    assert all(len(c) > 0 for c in result)
    rejoined = " ".join(result)
    assert "First sentence." in rejoined
    print("  PASS test_split_at_sentence_boundary")


def test_split_single_oversized_sentence_hard_split():
    # A single sentence with no boundaries is hard-split so that no segment
    # exceeds max_chars (overlong segments destabilise IndexTTS2 generation).
    text = "A" * 500 + "."
    result = TTSEngine._split_long_line(text, 400)
    assert len(result) >= 2, f"Expected a hard split, got {len(result)} chunk(s)"
    assert all(len(c) <= 400 for c in result), \
        f"Segment exceeds max_chars: {[len(c) for c in result]}"
    assert "".join(result) == text, "Hard split must not lose characters"
    print("  PASS test_split_single_oversized_sentence_hard_split")


def test_split_oversized_sentence_prefers_word_boundary():
    text = ("word " * 120).strip() + "."   # ~600 chars, no sentence breaks
    result = TTSEngine._split_long_line(text, 400)
    assert all(len(c) <= 400 for c in result), \
        f"Segment exceeds max_chars: {[len(c) for c in result]}"
    assert all(not c.startswith("ord") for c in result), "Split mid-word"
    print("  PASS test_split_oversized_sentence_prefers_word_boundary")


def test_split_multi_sentence_packs_greedily():
    sentence = "X" * 78 + ". "
    text = (sentence * 5).rstrip()
    result = TTSEngine._split_long_line(text, 200)
    assert len(result) >= 2, f"Expected multiple chunks, got {result}"
    for chunk in result:
        assert len(chunk) <= 200 or " " not in chunk, (
            f"Chunk exceeds max_chars with a split point available: {len(chunk)}"
        )
    print("  PASS test_split_multi_sentence_packs_greedily")


# ── _concat_wavs tests ────────────────────────────────────────────────────────

def test_concat_wavs_valid_output():
    a = _wav_silence(duration_ms=100)
    b = _wav_silence(duration_ms=200)
    result = TTSEngine._concat_wavs([a, b])
    assert result[:4] == b"RIFF", "Output must start with RIFF header"
    assert result[8:12] == b"WAVE"
    print("  PASS test_concat_wavs_valid_output")


def test_concat_wavs_frame_count():
    import wave as _w, io as _io
    def _frames(raw):
        with _w.open(_io.BytesIO(raw), "rb") as wf:
            return wf.getnframes()

    a = _wav_silence(duration_ms=100)
    b = _wav_silence(duration_ms=200)
    combined = TTSEngine._concat_wavs([a, b])
    assert _frames(combined) == _frames(a) + _frames(b), (
        f"Expected {_frames(a) + _frames(b)} frames, got {_frames(combined)}"
    )
    print("  PASS test_concat_wavs_frame_count")


def test_process_chapter_splits_long_line():
    """A line exceeding max_line_chars must call _synthesize once per segment
    and save a single WAV file for the line."""
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    long_text = ("The Sovereign watched as the shadows converged. " * 10).rstrip()
    assert len(long_text) > 400, "Test setup: text must exceed max_line_chars"

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": long_text, "emotion": "neutral"},
    ])

    call_count = [0]
    def counting_synth(text, ref, ref_text="", emo_vector=None, emo_alpha=0.0):
        call_count[0] += 1
        return _wav_silence(duration_ms=50)

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=counting_synth)
        n = engine.process_chapter(ch_id)

        assert n == 1, f"Expected 1 line synthesised, got {n}"
        assert call_count[0] > 1, (
            f"Expected multiple _synthesize calls for split line, got {call_count[0]}"
        )
        wav_path = Path(out_dir) / f"ch_{ch_id:04d}" / "line_0000.wav"
        assert wav_path.exists(), "Output WAV must exist"

    ref_wav.unlink(missing_ok=True)
    print(f"  PASS test_process_chapter_splits_long_line ({call_count[0]} segments)")


# ── _normalize_text smoke test ────────────────────────────────────────────────

def test_normalize_keeps_emphasised_words():
    # Regression: *enormous* must keep its content — only known stage
    # directions like *sighs* are deleted outright.
    out = _normalize_text("It was *enormous*.")
    assert "enormous" in out, f"Emphasised word was deleted: {out!r}"
    out2 = _normalize_text("*sighs* Fine, I will go.")
    assert "sighs" not in out2.lower(), f"Stage direction not removed: {out2!r}"
    assert "Fine, I will go" in out2
    print("  PASS test_normalize_keeps_emphasised_words")


def test_normalize_text_basic():
    out = _normalize_text("“Hello—world…”")
    assert "—" not in out and "…" not in out and "“" not in out
    assert out.endswith(".") or out.endswith('"')
    print("  PASS test_normalize_text_basic")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_emotion_vocab_all_mapped,
    test_resolve_emotion_neutral_is_pure_timbre,
    test_resolve_emotion_unknown_is_pure_timbre,
    test_resolve_emotion_angry_has_anger_component,
    test_synthesize_receives_emotion_vector,
    test_emo_alpha_scale_applied,
    test_resolve_ref_audio_primary,
    test_resolve_ref_audio_emotion_override,
    test_resolve_ref_audio_falls_back_to_primary,
    test_resolve_ref_audio_missing_returns_none,
    test_resolve_ref_audio_falls_back_to_default,
    test_resolve_ref_audio_dict_entry,
    test_wav_silence_is_valid_wav,
    test_synthesize_requires_loaded_model,
    test_load_model_requires_model_dir,
    test_back_compat_fish_speech_dir_kwarg,
    test_process_chapter_generates_wav_files,
    test_process_chapter_skips_missing_voice,
    test_process_chapter_retries_on_failure,
    test_process_chapter_marks_failed_after_all_retries,
    test_process_chapter_empty_no_crash,
    test_process_chapter_uses_default_fallback,
    test_emotion_override_voice_used,
    test_split_short_line_unchanged,
    test_split_at_sentence_boundary,
    test_split_single_oversized_sentence_hard_split,
    test_split_oversized_sentence_prefers_word_boundary,
    test_split_multi_sentence_packs_greedily,
    test_concat_wavs_valid_output,
    test_concat_wavs_frame_count,
    test_process_chapter_splits_long_line,
    test_normalize_text_basic,
    test_normalize_keeps_emphasised_words,
]

if __name__ == "__main__":
    print("Running Module 4 (IndexTTS2) tests...\n")
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
