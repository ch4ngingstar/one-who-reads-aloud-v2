"""
Test suite for Module 5: audio_assembler.py
Run: python tests/test_audio_assembler.py

No FFmpeg required — _run_ffmpeg and _check_ffmpeg are monkeypatched.
WAV helpers are tested with real wave data.
"""

import sys
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from audio_assembler import AudioAssembler, _DEFAULT_CFG


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_real_wav(path: Path, duration_ms: int = 100, sample_rate: int = 22050) -> Path:
    """Write a minimal but valid WAV (16-bit mono PCM) to path."""
    n_frames = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_chapter_with_tts_lines(sm, n_lines=3):
    """Seed project, diarize, and mark all lines as tts_done with real WAV paths."""
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 0,
            "title": "Ch 1",
            "chunks": [{"chunk_index": 0, "text": "x", "word_count": 1}],
        }],
    }
    pid   = sm.seed_project(book)
    ch_id = sm.get_all_chapters(pid)[0]["id"]

    speakers = ["Narrator", "Sunny", "Narrator"]
    sm.save_diarized_lines(ch_id, [
        {"line_index": i, "speaker": speakers[i % len(speakers)],
         "text": f"Line {i}.", "emotion": "neutral"}
        for i in range(n_lines)
    ])
    return pid, ch_id


def _make_assembler(sm, output_dir, mock_ffmpeg=True):
    asm = AudioAssembler(sm, output_dir)
    if mock_ffmpeg:
        asm._check_ffmpeg = lambda: None
        def fake_run(list_path, out_path):
            out_path.write_bytes(b"FAKE_AUDIO_DATA")
        asm._run_ffmpeg = fake_run
    return asm


# ── WAV helper unit tests ─────────────────────────────────────────────────────

def test_write_silence_wav_creates_valid_wav():
    import wave
    with tempfile.TemporaryDirectory() as tmp:
        src = _make_real_wav(Path(tmp) / "src.wav", duration_ms=100, sample_rate=22050)
        params = AudioAssembler._read_wav_params(src)

        sil = Path(tmp) / "silence.wav"
        AudioAssembler._write_silence_wav(params, duration_ms=200, out_path=sil)

        assert sil.exists()
        with wave.open(str(sil), "rb") as wf:
            assert wf.getframerate() == 22050
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            # 200ms at 22050 Hz = 4410 frames
            assert wf.getnframes() == 4410
            # All frames must be silence
            data = wf.readframes(wf.getnframes())
            assert set(data) == {0}

    print("  PASS test_write_silence_wav_creates_valid_wav")


def test_read_wav_params_returns_correct_values():
    with tempfile.TemporaryDirectory() as tmp:
        src = _make_real_wav(Path(tmp) / "test.wav", duration_ms=50, sample_rate=44100)
        params = AudioAssembler._read_wav_params(src)
        assert params.framerate    == 44100
        assert params.nchannels    == 1
        assert params.sampwidth    == 2

    print("  PASS test_read_wav_params_returns_correct_values")


# ── Concat list unit tests ────────────────────────────────────────────────────

def test_build_concat_list_single_line():
    with tempfile.TemporaryDirectory() as tmp:
        sil_same    = Path(tmp) / "sil_200.wav"
        sil_speaker = Path(tmp) / "sil_380.wav"
        sil_same.touch(); sil_speaker.touch()

        silence_paths = {200: sil_same, 380: sil_speaker}
        lines = [{"line_index": 0, "speaker": "Narrator",
                  "audio_path": "/audio/ch_0001/line_0000.wav"}]

        asm = AudioAssembler.__new__(AudioAssembler)
        asm.cfg = dict(_DEFAULT_CFG)

        content = asm._build_concat_list(lines, silence_paths)
        entries = [l for l in content.splitlines() if l.strip()]
        assert len(entries) == 1
        assert "line_0000.wav" in entries[0]

    print("  PASS test_build_concat_list_single_line")


def test_build_concat_list_same_speaker_uses_short_gap():
    with tempfile.TemporaryDirectory() as tmp:
        sil_same    = Path(tmp) / "sil_200.wav"
        sil_speaker = Path(tmp) / "sil_380.wav"
        sil_same.touch(); sil_speaker.touch()

        silence_paths = {200: sil_same, 380: sil_speaker}
        lines = [
            {"line_index": 0, "speaker": "Narrator",
             "audio_path": "/audio/line_0000.wav"},
            {"line_index": 1, "speaker": "Narrator",
             "audio_path": "/audio/line_0001.wav"},
        ]

        asm = AudioAssembler.__new__(AudioAssembler)
        asm.cfg = dict(_DEFAULT_CFG)

        content = asm._build_concat_list(lines, silence_paths)
        entries = content.splitlines()
        # Structure: [line0, silence, line1]
        assert len(entries) == 3
        assert "sil_200" in entries[1]

    print("  PASS test_build_concat_list_same_speaker_uses_short_gap")


def test_build_concat_list_speaker_change_uses_long_gap():
    with tempfile.TemporaryDirectory() as tmp:
        sil_same    = Path(tmp) / "sil_200.wav"
        sil_speaker = Path(tmp) / "sil_380.wav"
        sil_same.touch(); sil_speaker.touch()

        silence_paths = {200: sil_same, 380: sil_speaker}
        lines = [
            {"line_index": 0, "speaker": "Narrator",
             "audio_path": "/audio/line_0000.wav"},
            {"line_index": 1, "speaker": "Sunny",
             "audio_path": "/audio/line_0001.wav"},
        ]

        asm = AudioAssembler.__new__(AudioAssembler)
        asm.cfg = dict(_DEFAULT_CFG)

        content = asm._build_concat_list(lines, silence_paths)
        entries = content.splitlines()
        assert len(entries) == 3
        assert "sil_380" in entries[1], f"Expected long gap, got: {entries[1]}"

    print("  PASS test_build_concat_list_speaker_change_uses_long_gap")


def test_build_concat_list_three_lines_correct_entry_count():
    with tempfile.TemporaryDirectory() as tmp:
        sil_same    = Path(tmp) / "sil_200.wav"
        sil_speaker = Path(tmp) / "sil_380.wav"
        sil_same.touch(); sil_speaker.touch()

        silence_paths = {200: sil_same, 380: sil_speaker}
        lines = [
            {"line_index": i, "speaker": "Narrator",
             "audio_path": f"/audio/line_{i:04d}.wav"}
            for i in range(5)
        ]

        asm = AudioAssembler.__new__(AudioAssembler)
        asm.cfg = dict(_DEFAULT_CFG)

        content = asm._build_concat_list(lines, silence_paths)
        entries = content.splitlines()
        # 5 audio lines + 4 silences between them = 9 entries
        assert len(entries) == 9, f"Expected 9 entries, got {len(entries)}"

    print("  PASS test_build_concat_list_three_lines_correct_entry_count")


# ── FFmpeg command tests ──────────────────────────────────────────────────────

def test_build_ffmpeg_cmd_contains_required_flags():
    sm  = _tmp_sm()
    asm = AudioAssembler(sm, "/output")
    cmd = asm._build_ffmpeg_cmd(Path("/tmp/list.txt"), Path("/output/ch_0001.mp3"))

    assert "ffmpeg"  in cmd
    assert "-f"      in cmd
    assert "concat"  in cmd
    assert "-safe"   in cmd
    assert "-ar"     in cmd
    assert "320k"    in cmd
    assert "-filter:a" not in cmd  # loudnorm removed to preserve voice quality

    print("  PASS test_build_ffmpeg_cmd_contains_required_flags")


def test_build_ffmpeg_cmd_wav_format_no_bitrate():
    sm  = _tmp_sm()
    asm = AudioAssembler(sm, "/output", cfg={"output_format": "wav"})
    cmd = asm._build_ffmpeg_cmd(Path("/tmp/list.txt"), Path("/output/ch_0001.wav"))

    assert "320k" not in cmd, "WAV format should not include -b:a flag"
    assert str(Path("/output/ch_0001.wav")) in cmd

    print("  PASS test_build_ffmpeg_cmd_wav_format_no_bitrate")


# ── Integration tests (mocked FFmpeg + real WAVs) ─────────────────────────────

def test_assemble_chapter_creates_output_file():
    sm = _tmp_sm()
    pid, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=3)

    with tempfile.TemporaryDirectory() as wav_dir, \
         tempfile.TemporaryDirectory() as out_dir:

        # Give each line a real WAV file path
        lines = sm.get_pending_tts_lines(ch_id)
        for i, line in enumerate(lines):
            wav = _make_real_wav(Path(wav_dir) / f"line_{i:04d}.wav")
            sm.mark_line_tts_done(line["id"], str(wav))

        asm = _make_assembler(sm, out_dir)
        result = asm.assemble_chapter(ch_id)

        assert Path(result).exists()
        assert "ch_" in Path(result).name
        assert Path(result).name.endswith(".mp3")

    chapter = sm.get_all_chapters(pid)[0]
    assert chapter["status"]           == "complete"
    assert chapter["output_audio_path"] is not None

    print("  PASS test_assemble_chapter_creates_output_file")


def test_assemble_chapter_skips_failed_lines():
    sm = _tmp_sm()
    pid, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=4)

    with tempfile.TemporaryDirectory() as wav_dir, \
         tempfile.TemporaryDirectory() as out_dir:

        lines = sm.get_pending_tts_lines(ch_id)
        # Mark 3 as done, 1 as failed
        for i, line in enumerate(lines[:3]):
            wav = _make_real_wav(Path(wav_dir) / f"line_{i:04d}.wav")
            sm.mark_line_tts_done(line["id"], str(wav))
        sm.mark_line_failed(lines[3]["id"], "error")

        asm = _make_assembler(sm, out_dir)
        result = asm.assemble_chapter(ch_id)

        assert Path(result).exists()

    print("  PASS test_assemble_chapter_skips_failed_lines")


def test_assemble_chapter_raises_below_threshold():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=4)

    with tempfile.TemporaryDirectory() as wav_dir, \
         tempfile.TemporaryDirectory() as out_dir:

        lines = sm.get_pending_tts_lines(ch_id)
        # Only 1/4 lines done = 25% < default threshold of 50%
        wav = _make_real_wav(Path(wav_dir) / "line_0000.wav")
        sm.mark_line_tts_done(lines[0]["id"], str(wav))
        for line in lines[1:]:
            sm.mark_line_failed(line["id"], "error")

        asm = _make_assembler(sm, out_dir)
        try:
            asm.assemble_chapter(ch_id)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "threshold" in str(e).lower() or "%" in str(e)

    print("  PASS test_assemble_chapter_raises_below_threshold")


def test_assemble_chapter_raises_with_zero_lines():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=2)

    with tempfile.TemporaryDirectory() as out_dir:
        # No lines marked as tts_done
        asm = _make_assembler(sm, out_dir)
        try:
            asm.assemble_chapter(ch_id)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "no synthesised" in str(e).lower()

    print("  PASS test_assemble_chapter_raises_with_zero_lines")


def test_assemble_chapter_records_file_size():
    """After assembly, output_file_size_bytes should be stored in the DB."""
    sm = _tmp_sm()
    pid, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=2)

    with tempfile.TemporaryDirectory() as wav_dir, \
         tempfile.TemporaryDirectory() as out_dir:

        lines = sm.get_pending_tts_lines(ch_id)
        for i, line in enumerate(lines):
            wav = _make_real_wav(Path(wav_dir) / f"line_{i:04d}.wav")
            sm.mark_line_tts_done(line["id"], str(wav))

        asm = _make_assembler(sm, out_dir)
        asm.assemble_chapter(ch_id)

    chapter = sm.get_all_chapters(pid)[0]
    assert chapter["output_file_size_bytes"] is not None
    assert chapter["output_file_size_bytes"] > 0
    print("  PASS test_assemble_chapter_records_file_size")


def test_assemble_chapter_ffmpeg_receives_correct_list():
    """Verify the file list passed to FFmpeg contains all line audio paths."""
    sm = _tmp_sm()
    _, ch_id = _seed_chapter_with_tts_lines(sm, n_lines=2)

    with tempfile.TemporaryDirectory() as wav_dir, \
         tempfile.TemporaryDirectory() as out_dir:

        lines = sm.get_pending_tts_lines(ch_id)
        wav_paths = []
        for i, line in enumerate(lines):
            wav = _make_real_wav(Path(wav_dir) / f"line_{i:04d}.wav")
            sm.mark_line_tts_done(line["id"], str(wav))
            wav_paths.append(wav)

        captured_list = [None]

        def capture_run(list_path, out_path):
            captured_list[0] = list_path.read_text(encoding="utf-8")
            out_path.write_bytes(b"FAKE")

        asm = _make_assembler(sm, out_dir, mock_ffmpeg=False)
        asm._check_ffmpeg = lambda: None
        asm._run_ffmpeg   = capture_run
        asm.assemble_chapter(ch_id)

        assert captured_list[0] is not None
        for wp in wav_paths:
            assert wp.as_posix() in captured_list[0], (
                f"WAV path not in file list: {wp}"
            )

    print("  PASS test_assemble_chapter_ffmpeg_receives_correct_list")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_write_silence_wav_creates_valid_wav,
    test_read_wav_params_returns_correct_values,
    test_build_concat_list_single_line,
    test_build_concat_list_same_speaker_uses_short_gap,
    test_build_concat_list_speaker_change_uses_long_gap,
    test_build_concat_list_three_lines_correct_entry_count,
    test_build_ffmpeg_cmd_contains_required_flags,
    test_build_ffmpeg_cmd_wav_format_no_bitrate,
    test_assemble_chapter_creates_output_file,
    test_assemble_chapter_skips_failed_lines,
    test_assemble_chapter_raises_below_threshold,
    test_assemble_chapter_raises_with_zero_lines,
    test_assemble_chapter_records_file_size,
    test_assemble_chapter_ffmpeg_receives_correct_list,
]

if __name__ == "__main__":
    print("Running Module 5 tests...\n")
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
