"""
Test suite for Module 4: tts_engine.py
Run: python tests/test_tts_engine.py

No GPU / no Fish Speech server required — _synthesize and _wait_for_server
are monkeypatched in all integration tests.
"""

import sys
import struct
import tempfile
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from tts_engine import TTSEngine, _EMOTION_HINTS, _wav_silence, _encode_audio_b64


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    """Create TTSEngine with managed_server=False and optional mocked _synthesize."""
    engine = TTSEngine(
        state_manager=sm,
        output_dir=output_dir,
        managed_server=False,
        server_url="http://127.0.0.1:9999",
    )
    engine._wait_for_server = lambda: None  # bypass health check
    if mock_synth is not None:
        engine._synthesize = mock_synth
    return engine


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_emotion_hints_all_valid():
    # _EMOTION_HINTS is intentionally empty: Fish Speech V1.5 reads parenthetical
    # style cues aloud as literal words. Emotion is conveyed via reference clip
    # selection ({speaker}_{emotion} key), not text prefixes.
    assert _EMOTION_HINTS == {}, f"_EMOTION_HINTS must be empty, got: {_EMOTION_HINTS}"
    print("  PASS test_emotion_hints_all_valid")


def test_apply_emotion_hint_neutral():
    engine = TTSEngine.__new__(TTSEngine)
    result = engine._apply_emotion_hint("Hello world.", "neutral")
    assert result == "Hello world.", f"Neutral should not modify text, got: {result!r}"
    print("  PASS test_apply_emotion_hint_neutral")


def test_apply_emotion_hint_whispers():
    # Emotion hints removed — all emotions return text unmodified.
    engine = TTSEngine.__new__(TTSEngine)
    result = engine._apply_emotion_hint("Stay quiet.", "whispers")
    assert result == "Stay quiet.", f"No hint expected for any emotion, got: {result!r}"
    print("  PASS test_apply_emotion_hint_whispers")


def test_resolve_ref_audio_primary():
    voice_map = {"Sunny": "/voices/sunny.wav", "Narrator": "/voices/narrator.wav"}
    result = TTSEngine._resolve_ref_audio("Sunny", "neutral", voice_map)
    assert result == ("/voices/sunny.wav", ""), f"Got: {result}"
    print("  PASS test_resolve_ref_audio_primary")


def test_resolve_ref_audio_emotion_override():
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


def test_wav_silence_is_valid_wav():
    wav = _wav_silence(duration_ms=100)
    # Check RIFF header
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) > 44
    print("  PASS test_wav_silence_is_valid_wav")


def test_encode_audio_b64():
    wav_path = _tmp_wav()
    b64 = _encode_audio_b64(wav_path)
    decoded = base64.b64decode(b64)
    assert decoded[:4] == b"RIFF"
    wav_path.unlink(missing_ok=True)
    print("  PASS test_encode_audio_b64")


# ── Integration tests (mocked server) ────────────────────────────────────────

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
        engine = _make_engine(sm, out_dir, mock_synth=lambda t, r, rt="": _wav_silence())
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
    # Only Narrator has a voice, Sunny does not
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": "Scene begins.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "No voice set.", "emotion": "neutral"},
    ])

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=lambda t, r, rt="": _wav_silence())
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
    def flaky_synth(text, ref, ref_text=""):
        call_count[0] += 1
        if call_count[0] < 2:
            raise ConnectionError("Server timeout")
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

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=lambda t, r, rt="": (_ for _ in ()).throw(RuntimeError("VRAM OOM")))
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
    # Mark the line as already done
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
    sm.set_voice("_default", str(ref_wav))  # only default registered

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Sunny", "text": "Uses default.", "emotion": "neutral"},
    ])

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=lambda t, r, rt="": _wav_silence())
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
    def capture_synth(text, ref, ref_text=""):
        used_refs.append(ref)
        return _wav_silence()

    with tempfile.TemporaryDirectory() as out_dir:
        engine = _make_engine(sm, out_dir, mock_synth=capture_synth)
        engine.process_chapter(ch_id)

    assert used_refs[0] == str(ref_quiet), (
        f"Expected whisper ref, got: {used_refs[0]}"
    )
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
    # All original content must survive (minus the split spaces)
    assert "First sentence." in rejoined
    print("  PASS test_split_at_sentence_boundary")


def test_split_single_oversized_sentence_kept_intact():
    # One sentence longer than max_chars — no split point, must return [text]
    text = "A" * 500 + "."
    result = TTSEngine._split_long_line(text, 400)
    assert result == [text], f"Should return [text] unchanged, got {len(result)} chunks"
    print("  PASS test_split_single_oversized_sentence_kept_intact")


def test_split_multi_sentence_packs_greedily():
    # 5 sentences of 80 chars each — with max_chars=200, should pack 2 per chunk
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


# ── Splitting integration test ────────────────────────────────────────────────

def test_process_chapter_splits_long_line():
    """A line exceeding max_line_chars must call _synthesize once per segment
    and save a single WAV file for the line."""
    sm = _tmp_sm()
    ref_wav = _tmp_wav()
    sm.set_voice("Narrator", str(ref_wav))

    # Build a line that is > 400 chars with clear sentence boundaries
    long_text = ("The Sovereign watched as the shadows converged. " * 10).rstrip()
    assert len(long_text) > 400, "Test setup: text must exceed max_line_chars"

    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Narrator", "text": long_text, "emotion": "neutral"},
    ])

    call_count = [0]
    def counting_synth(text, ref, ref_text=""):
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
    print(f"  PASS test_process_chapter_splits_long_line "
          f"({call_count[0]} segments)")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_emotion_hints_all_valid,
    test_apply_emotion_hint_neutral,
    test_apply_emotion_hint_whispers,
    test_resolve_ref_audio_primary,
    test_resolve_ref_audio_emotion_override,
    test_resolve_ref_audio_falls_back_to_primary,
    test_resolve_ref_audio_missing_returns_none,
    test_resolve_ref_audio_falls_back_to_default,
    test_wav_silence_is_valid_wav,
    test_encode_audio_b64,
    test_process_chapter_generates_wav_files,
    test_process_chapter_skips_missing_voice,
    test_process_chapter_retries_on_failure,
    test_process_chapter_marks_failed_after_all_retries,
    test_process_chapter_empty_no_crash,
    test_process_chapter_uses_default_fallback,
    test_emotion_override_voice_used,
    test_split_short_line_unchanged,
    test_split_at_sentence_boundary,
    test_split_single_oversized_sentence_kept_intact,
    test_split_multi_sentence_packs_greedily,
    test_concat_wavs_valid_output,
    test_concat_wavs_frame_count,
    test_process_chapter_splits_long_line,
]

if __name__ == "__main__":
    print("Running Module 4 tests...\n")
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
