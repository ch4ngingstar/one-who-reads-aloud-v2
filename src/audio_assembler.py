"""
Module 5: Audio Assembler
===========================
Concatenates per-line WAV files into a single chapter MP3 using FFmpeg.
Uses the labelled text to time pauses between dialogue and narration.

CPU-only assembly can run while the speech engine is resident.

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

from datetime import datetime, timezone
import re
import subprocess
import json
import uuid
import tempfile
import wave
from pathlib import Path

from chapter_titles import book_folder, chapter_filename, identify, safe_name
from state_manager import StateManager, _resolve_stored_path
from sound_designer import SoundDesigner
from pacing import NATURAL_PAUSES, mark_paragraphs, pause_ms
from speech_audio import tighten_edges
from performance_score import write_json


def chapter_heading(title: str) -> str:
    """'Chapter 1994  Call to Arms' -> 'Chapter 1994: Call to Arms' (see chapter_titles.identify)."""
    return identify(title).display


def volume_album(book_title: str, project_name: str) -> str:
    """'Shadow Slave' + '...-vol9-c1841-c2260' -> 'Shadow Slave, Volume 9'."""
    volume = re.search(r"(?i)vol(?:ume)?[ ._-]*(\d+)", project_name or "")
    if volume:
        return f"{book_title}, Volume {int(volume.group(1))}".lstrip(", ")
    return book_title or project_name


def _concat_entry(p: Path) -> str:
    """FFmpeg concat-demuxer entry with single quotes escaped ('\\'')."""
    return "file '{}'".format(p.as_posix().replace("'", r"'\''"))


# Cue types stored in the DB map onto the three sound-design categories the user
# can enable/disable independently. (A "scene" cue lays an ambience bed.)
_CUE_TYPE_TO_CATEGORY = {"scene": "ambience", "sfx": "sfx", "music": "music"}


# ── Config defaults ───────────────────────────────────────────────────────────
_DEFAULT_CFG = {
    "inter_line_silence_ms":    200,   # legacy gap between raw takes, same speaker
    "inter_speaker_silence_ms": 380,   # legacy gap on speaker change
    # "natural": every take gets the same edge padding (engines differ by up to
    # 0.6 s) and pauses follow the book's paragraphs; "legacy": fixed gaps on raw takes.
    "pacing":                   "natural",
    "pauses":                   dict(NATURAL_PAUSES),
    # Chapter files carry their own titles so audiobook players list them properly.
    "tag_metadata":             True,
    "book_title":               "Shadow Slave",
    "author":                   "Guiltythree",
    # Name files after the book's real chapters ("Shadow Slave, Volume 9/1994 - Call to Arms.mp3")
    # instead of database ids ("ch_0407.mp3", which matched nothing a listener sees).
    "book_layout":              True,
    "output_format":            "mp3",
    "mp3_bitrate":              "320k",
    "output_sample_rate":       44100,
    "output_channels":          1,     # mono — smaller files, standard for audiobooks
    "min_completion_ratio":     1.0,
    # ── Sound design (opt-in; off => behaviour identical to before) ──
    "sfx_enabled":              False, # master switch — layer sound when cues exist
    # Which of the three layers to render when enabled. Empty => nothing (off).
    "sfx_categories":           ["ambience", "sfx", "music"],
    "sfx_dir":                  "data/sfx",
    "sfx_channels":             2,     # cinematic mix is stereo (beds need width)
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
        for line in tts_done:
            path = _resolve_stored_path(line["audio_path"])
            if not path.is_file():
                raise RuntimeError(f"Missing audio for line {line['line_index']}: {path}. Restart to repair.")

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
        output_path = self._output_path(chapter_id, ext)
        # A re-render publishes under the chapter's real name; the master it replaces is
        # moved to previous/ only once the new one is complete (see _retire_previous).

        print(f"[assemble] Chapter {chapter_id}: assembling {n_done} lines "
              f"-> {output_path.name}")

        # All work happens inside a temp dir (silence WAVs + file list)
        with tempfile.TemporaryDirectory(dir=self.output_dir) as tmp:
            tmp_path = Path(tmp)
            staged_output = tmp_path / output_path.name
            score_path = self.cfg.get("score_path")
            sheet = None
            if score_path and Path(score_path).is_file():
                from cast_mix import balance_cast
                sheet = json.loads(Path(score_path).read_text(encoding="utf-8"))
                tts_done, sheet["actor_gain_db"] = balance_cast(tts_done, sheet["cues"], tmp_path)
            if self._pauses() is not None:
                tts_done = self._tighten_edges(tts_done, tmp_path)
                mark_paragraphs(tts_done, [c["text"] for c in self.sm.get_chunks_for_chapter(chapter_id)])

            # Determine silence parameters from first source WAV
            first_wav_path = _resolve_stored_path(tts_done[0]["audio_path"])
            params = self._read_wav_params(first_wav_path)

            # Generate one silence WAV per distinct gap the chapter needs
            needed_gaps = {self._gap(a, b) for a, b in zip(tts_done, tts_done[1:])}
            silence_paths: dict[int, Path] = {}
            for ms in needed_gaps:
                sil_path = tmp_path / f"silence_{ms}ms.wav"
                self._write_silence_wav(params, ms, sil_path)
                silence_paths[ms] = sil_path

            # Build FFmpeg concat file list
            list_path = tmp_path / "filelist.txt"
            list_content = self._build_concat_list(tts_done, silence_paths)
            list_path.write_text(list_content, encoding="utf-8")

            # Master switch + per-category whitelist. A cue only survives if its
            # category is enabled; empty whitelist => no cues => default path.
            if self.cfg.get("sfx_enabled"):
                enabled = set(self.cfg.get("sfx_categories") or [])
                cues = [
                    c for c in self.sm.get_cues_for_chapter(chapter_id)
                    if _CUE_TYPE_TO_CATEGORY.get(c["cue_type"]) in enabled
                ]
            else:
                cues = []
            if cues:
                # Sound-design path: concat -> lossless voice bus, then mix
                # ambience/sfx/music under it (CPU-only, additive, never fatal).
                self._assemble_with_sound_design(
                    chapter_id, tts_done, list_path, tmp_path, staged_output, cues
                )
            else:
                # Default path — single-pass concat+encode, unchanged.
                self._run_ffmpeg(list_path, staged_output)

            # Publish only after the encoder has closed a usable file.
            actual_size = staged_output.stat().st_size if staged_output.exists() else 0
            if actual_size < 4096:
                raise RuntimeError(f"Assembly produced a suspiciously small file ({actual_size} bytes): {output_path}")
            if self.cfg.get("tag_metadata"):
                self._tag(staged_output, self._tags(chapter_id))
                actual_size = staged_output.stat().st_size
            # Keep the listening sheet after temporary line WAVs are cleaned up.
            if sheet is not None:
                timeline, total_ms = SoundDesigner().build_timeline(
                    tts_done, self.cfg["inter_line_silence_ms"], self.cfg["inter_speaker_silence_ms"],
                    self._pauses())
                sheet["duration_ms"] = round(total_ms)
                sheet["master_bytes"] = actual_size
                for cue in sheet["cues"]:
                    cue["start_ms"], cue["end_ms"] = map(round, timeline[cue["index"]])
                write_json(tmp_path / "performance.json", sheet)
            self._retire_previous(output_path)
            staged_output.replace(output_path)
            if sheet is not None:
                (tmp_path / "performance.json").replace(output_path.with_suffix(".performance.json"))
            else:
                output_path.with_suffix(".performance.json").unlink(missing_ok=True)

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
                sil = silence_paths[self._gap(sorted_lines[i - 1], line)]
                entries.append(_concat_entry(sil))

            audio_path = _resolve_stored_path(line["audio_path"]).resolve()
            entries.append(_concat_entry(audio_path))

        return "\n".join(entries)

    # ── Pacing ────────────────────────────────────────────────────────────────

    def _pauses(self) -> "dict | None":
        if self.cfg.get("pacing", "natural") != "natural":
            return None
        return self.cfg.get("pauses") or dict(NATURAL_PAUSES)

    def _gap(self, previous: dict, current: dict) -> int:
        return pause_ms(previous, current, self.cfg["inter_line_silence_ms"],
                        self.cfg["inter_speaker_silence_ms"], self._pauses())

    @staticmethod
    def _tighten_edges(lines: list, folder: Path) -> list:
        """Copies of the takes with uniform edge padding; the recorded takes stay untouched."""
        tightened = []
        for line in lines:
            source = _resolve_stored_path(line["audio_path"])
            dest = folder / f"edge_{line['line_index']:05d}.wav"
            dest.write_bytes(tighten_edges(source.read_bytes()))
            tightened.append({**line, "audio_path": str(dest)})
        return tightened

    # ── Metadata ──────────────────────────────────────────────────────────────

    def _chapter_identity(self, chapter_id: int):
        chapter = self.sm.get_chapter_by_id(chapter_id) or {}
        project = next((p["name"] for p in self.sm.list_projects() if p["id"] == chapter.get("project_id")), "")
        return chapter, identify(chapter.get("title") or f"Chapter {chapter_id}"), project

    @staticmethod
    def _retire_previous(output_path: Path) -> None:
        """Keep the master being replaced (and its timing sheet) in previous/, never delete it."""
        if not output_path.exists():
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        keep = output_path.parent / "previous"
        keep.mkdir(exist_ok=True)
        output_path.replace(keep / f"{output_path.stem} ({stamp}){output_path.suffix}")
        sheet = output_path.with_suffix(".performance.json")
        if sheet.exists():
            sheet.replace(keep / f"{output_path.stem} ({stamp}).performance.json")

    def _output_path(self, chapter_id: int, ext: str) -> Path:
        """Where a chapter's master goes: named by book and real chapter, or by id (legacy)."""
        if not self.cfg.get("book_layout", True):
            return self.output_dir / f"ch_{chapter_id:04d}.{ext}"
        chapter, identity, project = self._chapter_identity(chapter_id)
        folder = self.output_dir / book_folder(project or "Audiobook", self.cfg.get("book_title") or "Audiobook")
        folder.mkdir(parents=True, exist_ok=True)
        if identity.number is None and identity.kind != "front":
            # No chapter number to keep names unique: add the id rather than risk two
            # chapters sharing one file.
            return folder / f"{safe_name(identity.display)} [{chapter_id}].{ext}"
        return folder / chapter_filename(identity, ext)

    def _tags(self, chapter_id: int) -> dict:
        chapter, identity, project = self._chapter_identity(chapter_id)
        author = self.cfg.get("author") or ""
        album = volume_album(self.cfg.get("book_title") or "", project)
        return {"title": identity.display,
                "track": str(identity.number if identity.number is not None else chapter.get("chapter_index", "")),
                "album": album, "artist": author, "album_artist": author, "genre": "Audiobook"}

    @staticmethod
    def _tag(path: Path, tags: dict) -> None:
        """Rewrite the container with tags (stream copy). Untagged audio is kept on failure."""
        tagged = path.with_name("tagged_" + path.name)
        cmd = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(path), "-map", "0", "-c", "copy"]
        for key, value in tags.items():
            if value:
                cmd += ["-metadata", f"{key}={value}"]
        if path.suffix.lower() == ".mp3":
            cmd += ["-id3v2_version", "3"]
        cmd.append(str(tagged))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            print(f"[assemble] WARNING: chapter tags skipped ({exc})")
            return
        if result.returncode != 0 or not tagged.is_file() or tagged.stat().st_size < 4096:
            print(f"[assemble] WARNING: chapter tags skipped: {result.stderr.strip()[-200:]}")
            tagged.unlink(missing_ok=True)
            return
        tagged.replace(path)

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
        """Build the FFmpeg concat + encode command."""
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

    # ── Sound design (pass 2) ─────────────────────────────────────────────────

    def _assemble_with_sound_design(
        self,
        chapter_id: int,
        tts_done: list,
        list_path: Path,
        tmp_path: Path,
        output_path: Path,
        cues: list,
    ) -> None:
        """Concat to a lossless voice bus, then mix cues under it (SoundDesigner).

        The timeline is computed from the SAME line durations + silence gaps that
        were concatenated, so cue offsets are exact. Strictly additive: a failed
        mix falls back to encoding the plain voice bus inside SoundDesigner.render.
        """
        n_ch = int(self.cfg.get("sfx_channels", 2))
        voice_bus = tmp_path / "voice_bus.wav"
        self._run_voice_bus(list_path, voice_bus, n_ch)

        sd = SoundDesigner(cfg=self.cfg)
        timeline, _ = sd.build_timeline(
            tts_done,
            self.cfg["inter_line_silence_ms"],
            self.cfg["inter_speaker_silence_ms"],
            self._pauses(),
        )
        try:  # alias map is optional; cue_io ships it once Phase 5 lands
            from cue_io import SFX_TAG_ALIASES
        except Exception:
            SFX_TAG_ALIASES = {}

        resolved = sd.resolve_cues(
            cues, self.sm.get_sfx_map(), timeline, alias_map=SFX_TAG_ALIASES
        )
        print(f"[assemble] sound design: {len(resolved)}/{len(cues)} cues "
              f"applied -> {n_ch}ch mix")
        sd.render(voice_bus, resolved, output_path, n_channels=n_ch)

    def _run_voice_bus(self, list_path: Path, out_path: Path, n_channels: int) -> None:
        """Concat the line/silence WAVs into a lossless stereo voice bus."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-ar", str(self.cfg["output_sample_rate"]),
            "-ac", str(n_channels),
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg voice-bus concat failed (exit {result.returncode}):\n"
                f"{result.stderr[-1000:]}"
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
