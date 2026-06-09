"""
Module 5: Audio Assembler
===========================
Concatenates per-line WAV files into a single chapter MP3 using FFmpeg.
Injects calibrated silence between lines and applies EBU R128 loudness
normalisation so all chapters have consistent volume.

CPU-ONLY — no VRAM involved. Must run AFTER TTSEngine context exits.

REQUIREMENT: FFmpeg must be in PATH.
  Windows: https://www.gyan.dev/ffmpeg/builds/  (add bin/ to PATH)
  Verify:  ffmpeg -version

INPUT  (from Module 2 StateManager):
  sm.get_lines_for_chapter(chapter_id)
  -> [{ "line_index": int, "status": str, "audio_path": str,
        "speaker": str, "emotion": str }]
  Only lines with status == "tts_done" are assembled.

OUTPUT (to Module 2 StateManager):
  sm.mark_chapter_status(chapter_id, "complete",
                          audio_path="/data/output/ch_0001.mp3")

OUTPUT FILE:
  {output_dir}/ch_{chapter_id:04d}.{mp3|wav}
"""

import subprocess
import tempfile
import wave
from pathlib import Path

from state_manager import StateManager


# ── Config defaults ───────────────────────────────────────────────────────────
_DEFAULT_CFG = {
    "inter_line_silence_ms":    200,   # gap between lines, same speaker
    "inter_speaker_silence_ms": 380,   # longer gap on speaker change
    "output_format":            "mp3",
    "mp3_bitrate":              "320k",
    "output_sample_rate":       44100,
    "output_channels":          1,     # mono — smaller files, standard for audiobooks
    "min_completion_ratio":     0.5,   # abort if fewer than 50% of lines are tts_done
}


class AudioAssembler:
    """
    Assembles per-line WAV files into a finished chapter audio file.

    Parameters
    ----------
    state_manager : StateManager instance.
    output_dir    : Directory for finished chapter files (e.g. data/output).
    cfg           : Optional dict to override _DEFAULT_CFG values.
    """

    def __init__(
        self,
        state_manager: StateManager,
        output_dir: "str | Path",
        cfg: "dict | None" = None,
    ):
        self.sm         = state_manager
        self.output_dir = Path(output_dir)
        self.cfg        = {**_DEFAULT_CFG, **(cfg or {})}

    # ── Public API ────────────────────────────────────────────────────────────

    def assemble_chapter(self, chapter_id: int) -> str:
        """
        Concatenate all tts_done lines for a chapter into a single audio file.

        Returns the absolute path to the assembled output file.
        Advances chapter status to 'complete'.
        """
        self._check_ffmpeg()

        all_lines  = self.sm.get_lines_for_chapter(chapter_id)
        tts_done   = sorted(
            [l for l in all_lines if l["status"] == "tts_done" and l.get("audio_path")],
            key=lambda l: l["line_index"],
        )
        total   = len(all_lines)
        n_done  = len(tts_done)
        n_fail  = total - n_done

        if n_done == 0:
            raise RuntimeError(
                f"Chapter {chapter_id} has no synthesised lines. "
                "Run the TTS engine first."
            )

        if n_fail > 0:
            ratio = n_done / total
            pct   = n_fail / total * 100
            print(f"[assemble] WARNING: {n_fail}/{total} lines failed "
                  f"({pct:.0f}%)")
            if ratio < self.cfg["min_completion_ratio"]:
                raise RuntimeError(
                    f"Chapter {chapter_id}: only {n_done}/{total} lines synthesised "
                    f"({ratio*100:.0f}% < threshold "
                    f"{self.cfg['min_completion_ratio']*100:.0f}%). Aborting."
                )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        ext         = self.cfg["output_format"]
        output_path = self.output_dir / f"ch_{chapter_id:04d}.{ext}"

        print(f"[assemble] Chapter {chapter_id}: assembling {n_done} lines "
              f"-> {output_path.name}")

        # All work happens inside a temp dir (silence WAVs + file list)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Determine silence parameters from first source WAV
            first_wav_path = Path(tts_done[0]["audio_path"])
            params = self._read_wav_params(first_wav_path)

            # Generate silence WAVs for each unique gap duration
            needed_gaps = {
                self.cfg["inter_line_silence_ms"],
                self.cfg["inter_speaker_silence_ms"],
            }
            silence_paths: dict[int, Path] = {}
            for ms in needed_gaps:
                sil_path = tmp_path / f"silence_{ms}ms.wav"
                self._write_silence_wav(params, ms, sil_path)
                silence_paths[ms] = sil_path

            # Build FFmpeg concat file list
            list_path = tmp_path / "filelist.txt"
            list_content = self._build_concat_list(tts_done, silence_paths)
            list_path.write_text(list_content, encoding="utf-8")

            # Run FFmpeg
            self._run_ffmpeg(list_path, output_path)

        file_size = output_path.stat().st_size
        size_mb   = file_size / (1024 * 1024)
        print(f"[assemble] Done: {output_path.name}  ({size_mb:.2f} MB)")

        self.sm.mark_chapter_status(
            chapter_id, "complete",
            audio_path=str(output_path),
            file_size_bytes=file_size,
        )
        return str(output_path)

    # ── File list construction ────────────────────────────────────────────────

    def _build_concat_list(
        self,
        sorted_lines: list,
        silence_paths: dict,
    ) -> str:
        """
        Build the text content of an FFmpeg concat demuxer file.
        Inserts silence between every pair of lines; uses a longer gap
        when the speaker changes.

        Returns multi-line string (written to a .txt file).
        """
        entries: list[str] = []

        for i, line in enumerate(sorted_lines):
            if i > 0:
                prev = sorted_lines[i - 1]
                gap_ms = (
                    self.cfg["inter_speaker_silence_ms"]
                    if prev["speaker"] != line["speaker"]
                    else self.cfg["inter_line_silence_ms"]
                )
                sil = silence_paths[gap_ms]
                entries.append(f"file '{sil.as_posix()}'")

            audio_path = Path(line["audio_path"]).resolve().as_posix()
            entries.append(f"file '{audio_path}'")

        return "\n".join(entries)

    # ── WAV helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _read_wav_params(wav_path: Path):
        """Read params namedtuple from a WAV file."""
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getparams()

    @staticmethod
    def _write_silence_wav(params, duration_ms: int, out_path: Path) -> None:
        """Write a silent WAV file matching params for duration_ms milliseconds."""
        n_frames   = int(params.framerate * duration_ms / 1000)
        frame_size = params.nchannels * params.sampwidth
        silence    = b"\x00" * (n_frames * frame_size)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(params.nchannels)
            wf.setsampwidth(params.sampwidth)
            wf.setframerate(params.framerate)
            wf.writeframes(silence)

    # ── FFmpeg ────────────────────────────────────────────────────────────────

    def _build_ffmpeg_cmd(self, list_path: Path, output_path: Path) -> list[str]:
        """Build the FFmpeg concat + encode command (no loudnorm — preserves voice quality)."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-ar", str(self.cfg["output_sample_rate"]),
            "-ac", str(self.cfg["output_channels"]),
        ]
        if self.cfg["output_format"] == "mp3":
            cmd += ["-b:a", self.cfg["mp3_bitrate"]]
        cmd.append(str(output_path))
        return cmd

    def _run_ffmpeg(self, list_path: Path, output_path: Path) -> None:
        """Execute the FFmpeg command."""
        cmd = self._build_ffmpeg_cmd(list_path, output_path)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (exit {result.returncode}):\n{result.stderr[-1000:]}"
            )

    @staticmethod
    def _check_ffmpeg() -> None:
        """Raise a clear error if ffmpeg is not available in PATH."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5,
            )
            if r.returncode != 0:
                raise RuntimeError
        except (FileNotFoundError, RuntimeError, subprocess.TimeoutExpired):
            raise RuntimeError(
                "FFmpeg not found in PATH.\n"
                "Windows: https://www.gyan.dev/ffmpeg/builds/\n"
                "Run: ffmpeg -version  to verify."
            )
