"""
Module 4: TTS Engine (Fish Speech V1.5)
=========================================
Reads diarized lines from the DB, synthesises each line as a WAV file
using Fish Speech V1.5 zero-shot voice cloning, and writes results back.

SETUP (one-time):
  1. Clone:   git clone https://github.com/fishaudio/fish-speech
  2. Install: cd fish-speech && pip install -e ".[inference]"
  3. Weights: huggingface-cli download fishaudio/fish-speech-1.5
              --local-dir checkpoints/fish-speech-1.5

VOICE CLONING REFERENCE AUDIO:
  - 5–10 second clean WAV per character, stored anywhere you like.
  - Register via StateManager:  sm.set_voice("Sunny", "/voices/sunny.wav")
  - Emotion overrides (optional): sm.set_voice("Sunny_whispers", "/path/quiet.wav")
    The engine resolves "{Speaker}_{emotion}" first, falls back to "{Speaker}".

VRAM LIFECYCLE (Hardware Enforcer):
  This engine launches the Fish Speech API server as a subprocess.
  __enter__  -> server starts  -> model loads into VRAM  (~5 GB)
  __exit__   -> server killed  -> VRAM fully released
  LLM must be unloaded BEFORE entering this context.

  with TTSEngine(sm, output_dir, fish_speech_dir="fish-speech") as engine:
      engine.process_chapter(chapter_id)
  # <- server killed here, VRAM clear

INPUT  (from Module 2 StateManager):
  sm.get_pending_tts_lines(chapter_id)
  -> [{ "id": int, "line_index": int, "speaker": str,
        "text": str, "emotion": str }]

  sm.get_voice_map()
  -> { "Speaker": "/path/to/ref.wav", ... }

OUTPUT (to Module 2 StateManager):
  sm.mark_line_tts_done(line_id, audio_path)
  sm.mark_line_failed(line_id, error_message)
  sm.mark_chapter_status(chapter_id, "tts_done")

OUTPUT FILES:
  {output_dir}/ch_{chapter_id:04d}/line_{line_index:04d}.wav
"""

import base64
import gc
import io
import json
import os
import re
import subprocess
import sys
import time
import wave as _wave_mod
from pathlib import Path
from typing import Callable, Optional

try:
    import requests as _requests_lib
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

from state_manager import StateManager


# Fish Speech V1.5 is a voice cloner — it derives prosody from the reference
# audio, not from text markers.  Parenthetical style cues like "(coldly) " or
# "(frightened) " are read aloud as literal words, which is a bug.
# Emotion is handled by selecting an emotion-specific reference clip (see
# _resolve_ref_audio: it checks "{speaker}_{emotion}" first).
# Do NOT re-introduce text prefixes here.
_EMOTION_HINTS: dict[str, str] = {}  # intentionally empty

# ── Speaker alias dictionary ──────────────────────────────────────────────────
# Maps every title / alias the LLM may output → the canonical voice key.
# Keys MUST be in Title Case (matching the .strip().title() normalisation below).
SPEAKER_ALIASES: dict[str, str] = {
    # Sunny & his many titles
    "Sunless":            "Sunny",
    "Lost From Light":    "Sunny",
    "Lord Of Shadows":    "Sunny",
    "The Shopkeeper":     "Sunny",
    "Master Sunless":     "Sunny",
    "Shadow":             "Sunny",
    "Treacherous Shadow": "Sunny",
    "Mongrel":            "Sunny",
    "Devil Of Antarctica":"Sunny",
    "Weaver'S Heir":      "Sunny",   # title() turns ' → 'S

    # The Divine Cohort
    "Neph":               "Nephis",
    "Changing Star":      "Nephis",
    "Light":              "Nephis",
    "Lady Nephis":        "Nephis",
    "Saint Nephis":       "Nephis",

    "Cassia":             "Cassie",
    "Song Of The Fallen": "Cassie",
    "Blind Girl":         "Cassie",
    "Seer":               "Cassie",
    "Saint Cassia":       "Cassie",

    "Athena":             "Effie",
    "Raised By Wolves":   "Effie",
    "Saint Effie":        "Effie",

    "Nightingale":        "Kai",
    "Master Kai":         "Kai",
    "Saint Kai":          "Kai",

    "Soul Reaper":        "Jet",
    "Master Jet":         "Jet",
    "Saint Jet":          "Jet",
    "Boss":               "Jet",

    "Prince Of Nothing":  "Mordret",

    # The Sovereigns & Clan Leaders
    "Anvil":              "Lord Valor",
    "King Anvil":         "Lord Valor",
    "King Of Swords":     "Lord Valor",
    "Lord Of Swords":     "Lord Valor",
    "Anvil Of Valor":     "Lord Valor",

    "Ki Song":            "Queen Ki Song",
    "Queen Of Beasts":    "Queen Ki Song",
    "Queen Of Song":      "Queen Ki Song",

    # Domain War Saints & Legacies
    "Morgan Of Valor":    "Morgan",
    "Princess Morgan":    "Morgan",
    "Saint Morgan":       "Morgan",

    "Sky Tide":           "Tyris",
    "Saint Tyris":        "Tyris",

    "Saint Roan":         "Roan",

    "Saint Beastmaster":  "Beastmaster",

    "Revel":              "Revel Of Song",
    "Dirge":              "Revel Of Song",
    "Saint Revel":        "Revel Of Song",

    # The Godgrave Cohort
    "Tamar":              "Tamar Of Sorrow",
    "Lady Tamar":         "Tamar Of Sorrow",

    # Lore & Entities
    "Weaver":             "The Nightmare Spell",
    "The Spell":          "The Nightmare Spell",
    "System":             "The Nightmare Spell",
    "Spell":              "The Nightmare Spell",

    "Eurys":              "Eurys Of The Nine",

    # Academy / Past Mentors
    "Ram":                "Instructor Ram",
    "Julius":             "Instructor Ram",
    "Teacher Julius":     "Instructor Ram",

    # NPC Archetypes (LLM fallback tags)
    "Npc_Male":           "The Hardened Awakened",
    "Npc_Female":         "The Bureaucrat",
    "Npc_Noble":          "The Legacy Noble",
    "Npc_Wanderer":       "The Dream Realm Wanderer",
    "Npc_Monster":        "The Nightmare Abomination",
    "Unknown":            "_default",

    # Corrupted / monster entities
    "Abomination":        "The Nightmare Abomination",
    "Corrupted":          "The Nightmare Abomination",
    "The Abomination":    "The Nightmare Abomination",
    "Monster":            "The Nightmare Abomination",
    "Nightmare Creature": "The Nightmare Abomination",
    "Void Creature":      "The Nightmare Abomination",
    "Corrupted Being":    "The Nightmare Abomination",
    "Shadow Creature":    "The Nightmare Abomination",
    "Hollow":             "The Nightmare Abomination",
    "Corrupted One":      "The Nightmare Abomination",
    "Fallen":             "The Nightmare Abomination",
    "Awakened Monster":   "The Nightmare Abomination",
    "Great Monster":      "The Nightmare Abomination",
    "Creature":           "The Nightmare Abomination",
    "Fiend":              "The Nightmare Abomination",
    "Demon":              "The Nightmare Abomination",
    "Scavenger":          "The Nightmare Abomination",
}


# ── Default Fish Speech server config ────────────────────────────────────────
_DEFAULT_CFG = {
    "host":              "127.0.0.1",
    "port":              8080,
    "server_start_timeout": 90,    # seconds to wait for server ready
    "request_timeout":   120,      # seconds per TTS request (longer for complex lines)
    "max_retries":       3,        # retries on generation failure
    "sample_rate":       44100,    # target sample rate for output WAVs

    # ── Fish Speech V1.5 quality / stability params ──────────────────────────
    # Stabilizes voice cloning and reduces hallucinations/audio glitching.
    # Lower = more stable/consistent but slightly less expressive.
    # Tweak range: 0.60 (very stable, robotic risk) → 0.80 (natural, glitch risk).
    "temperature":       0.70,    # down from 0.72 → slightly more stable without losing naturalness

    # Restricts acoustic token sampling — keeps the output sounding strictly like
    # the reference file rather than drifting. Lower = tighter clone fidelity.
    # Tweak range: 0.75 (very tight) → 0.90 (more variation allowed).
    "top_p":             0.82,    # down from 0.85 → tighter clone fidelity

    # Critical for Fish Speech: prevents stuttering, echoing, and sentence-end
    # looping artifacts. Stay in 1.2–1.5; above 1.5 causes unnatural clipping.
    # Tweak range: 1.2 (light penalty) → 1.5 (aggressive, use if looping persists).
    "repetition_penalty": 1.30,   # up from 1.25 → stronger anti-loop for long Narrator lines

    "max_new_tokens":    4096,    # up from 2048 → prevents truncation of long Narrator passages
    "chunk_length":      200,     # larger = more prosody context; 100 caused choppy transitions
    "max_line_chars":    400,     # lines longer than this are split at sentence boundaries
}


def _encode_audio_b64(path: "str | Path") -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _normalize_text(text: str) -> str:
    """
    Clean up text for maximum TTS accuracy.
    Fixes Unicode typography, normalises whitespace, and handles
    common novel formatting that confuses speech synthesisers.
    """
    # Unicode quotes → ASCII
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    # Strip italic/emphasis markers but keep their content.
    # Only remove short pure-lowercase LLM stage directions like *sighs*, *pauses*.
    # All other *wrapped text* has its content preserved — dropping it loses story words.
    text = re.sub(r'\*([a-z]{1,20}s?)\*', '', text)          # *sighs* → gone
    text = re.sub(r'\*([^*]{1,120})\*', r'\1', text)          # *inner thought* → inner thought
    # Strip square brackets but KEEP their content.
    # The novel uses [Aspect of the Void], [Rank: X] etc — these must be spoken.
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)
    # Em-dash handling: mid-word interruption → ellipsis; mid-sentence → comma
    text = re.sub(r'(\w)—$', r'\1...', text)    # trailing "word—" → "word..." (interrupted speech)
    text = re.sub(r'(\w)—(\w)', r'\1, \2', text) # "word—word" → "word, word"
    text = text.replace('—', ', ')               # remaining standalone em-dashes → pause
    # En-dash → spaced hyphen
    text = text.replace('–', ' - ')
    # Horizontal ellipsis → three dots
    text = text.replace('…', '...')
    # Non-breaking space → regular space
    text = text.replace(' ', ' ')
    # Strip zero-width chars
    text = text.replace('​', '').replace('﻿', '')
    # Abbreviations (before punctuation normalization)
    for _pat, _rep in [
        (r'\bDr\.', 'Doctor'), (r'\bMr\.', 'Mister'), (r'\bMrs\.', 'Missus'),
        (r'\bMs\.', 'Miss'), (r'\bSt\.', 'Saint'), (r'\bvs\.', 'versus'),
        (r'\bapprox\.', 'approximately'), (r'\betc\.', 'and so on'),
    ]:
        text = re.sub(_pat, _rep, text)

    # Ordinal numbers
    for _abbr, _word in [
        ('1st','first'),('2nd','second'),('3rd','third'),('4th','fourth'),
        ('5th','fifth'),('6th','sixth'),('7th','seventh'),('8th','eighth'),
        ('9th','ninth'),('10th','tenth'),('11th','eleventh'),('12th','twelfth'),
    ]:
        text = re.sub(r'\b' + re.escape(_abbr) + r'\b', _word, text, flags=re.IGNORECASE)

    # Symbols
    text = re.sub(r'(\d+)\s*%', r'\1 percent', text)
    text = re.sub(r'\$(\d+)', r'\1 dollars', text)

    # Collapse multiple spaces / dangling punctuation from stripped markers
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'[,;]\s*$', '.', text)      # trailing comma/semicolon → period
    text = re.sub(r'(\w)$', lambda m: m.group(1) + '.', text)  # add period if no ending punctuation
    return text.strip()


def _wav_silence(duration_ms: int = 100, sample_rate: int = 44100) -> bytes:
    """Generate a minimal silent WAV file as a fallback placeholder."""
    import struct, math
    n_samples = int(sample_rate * duration_ms / 1000)
    data = b"\x00\x00" * n_samples  # 16-bit silence
    data_size = len(data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16,
        1,                    # PCM
        1,                    # mono
        sample_rate,
        sample_rate * 2,      # byte rate
        2,                    # block align
        16,                   # bits per sample
        b"data", data_size,
    )
    return header + data


# ── Main class ────────────────────────────────────────────────────────────────

class TTSEngine:
    """
    VRAM-safe TTS engine backed by Fish Speech V1.5.
    Must be used as a context manager.

    Parameters
    ----------
    state_manager      : StateManager instance.
    output_dir         : Root dir for WAV output files.
    fish_speech_dir    : Path to the cloned fish-speech repo.
                         Required when managed_server=True.
    server_url         : Base URL for the Fish Speech API server.
                         Only needed when managed_server=False (external server).
    managed_server     : If True (default), this class starts and stops the
                         Fish Speech server subprocess automatically.
                         If False, you must start the server externally.
    cfg                : Optional dict to override _DEFAULT_CFG values.
    """

    def __init__(
        self,
        state_manager: StateManager,
        output_dir: "str | Path",
        fish_speech_dir: "str | Path | None" = None,
        server_url: str = "http://127.0.0.1:8080",
        managed_server: bool = True,
        cfg: "dict | None" = None,
    ):
        self.sm               = state_manager
        self.output_dir       = Path(output_dir)
        self.fish_speech_dir  = Path(fish_speech_dir) if fish_speech_dir else None
        self.server_url       = server_url.rstrip("/")
        self.managed_server   = managed_server
        self.cfg              = {**_DEFAULT_CFG, **(cfg or {})}
        self._server_proc: Optional[subprocess.Popen] = None

    # ── Context manager (Hardware Enforcer) ───────────────────────────────────

    def __enter__(self):
        if self.managed_server:
            self._start_server()
        else:
            self._wait_for_server()
        print("[tts] Engine ready.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_server()
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            print("[tts] CUDA cache cleared.")
        except ImportError:
            pass
        print("[tts] VRAM released.")
        return False

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def _start_server(self) -> None:
        if self.fish_speech_dir is None:
            raise ValueError(
                "fish_speech_dir must be set when managed_server=True.\n"
                "Clone: git clone https://github.com/fishaudio/fish-speech"
            )
        fish_dir = self.fish_speech_dir.resolve()
        server_script = fish_dir / "tools" / "api_server.py"
        if not server_script.exists():
            raise FileNotFoundError(f"Fish Speech server script not found: {server_script}")

        host = self.cfg["host"]
        port = self.cfg["port"]
        cmd = [
            sys.executable, str(server_script),  # absolute path — safe regardless of cwd
            "--listen", f"{host}:{port}",
            "--device", "cuda",
        ]
        log_path = fish_dir / "fish_speech_server.log"
        print(f"[tts] Starting Fish Speech server on {host}:{port}...")
        print(f"[tts] Server log: {log_path}", flush=True)
        self._stderr_file = open(log_path, "w")
        self._server_proc = subprocess.Popen(
            cmd,
            cwd=str(fish_dir),
            stdout=self._stderr_file,
            stderr=subprocess.STDOUT,
        )
        print(f"[tts] Server PID: {self._server_proc.pid}", flush=True)
        self._wait_for_server()

    def _stop_server(self) -> None:
        if self._server_proc is not None:
            print("[tts] Stopping Fish Speech server...")
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
            self._server_proc = None
            print("[tts] Server stopped.")
        if hasattr(self, "_stderr_file") and self._stderr_file:
            self._stderr_file.close()
            self._stderr_file = None

    def _wait_for_server(self) -> None:
        """Poll /v1/health until the server responds or timeout."""
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError("requests library not installed: pip install requests")

        import requests
        deadline = time.time() + self.cfg["server_start_timeout"]
        print(f"[tts] Waiting for server at {self.server_url}...")
        while time.time() < deadline:
            # Fail fast if the subprocess has already exited
            if self._server_proc is not None and self._server_proc.poll() is not None:
                log_path = Path(getattr(self, "_stderr_file", None) and
                                self._stderr_file.name or "fish_speech_server.log")
                tail = ""
                try:
                    tail = log_path.read_text(errors="replace")[-2000:]
                except Exception:
                    pass
                raise RuntimeError(
                    f"Fish Speech server exited (code {self._server_proc.returncode}) "
                    f"before becoming ready.\nLast output:\n{tail}"
                )
            try:
                r = requests.get(f"{self.server_url}/v1/health", timeout=2)
                if r.status_code == 200:
                    print("[tts] Server is ready.")
                    return
            except Exception:
                pass
            time.sleep(2)
        raise TimeoutError(
            f"Fish Speech server did not become ready within "
            f"{self.cfg['server_start_timeout']}s at {self.server_url}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def process_chapter(
        self,
        chapter_id: int,
        progress_callback: "Callable[[int, int], None] | None" = None,
    ) -> int:
        """
        Synthesise all pending lines for a chapter.
        Returns the count of successfully generated lines.
        Advances chapter status to 'tts_done'.

        progress_callback(lines_processed, lines_total) is called after every line.
        """
        lines     = self.sm.get_pending_tts_lines(chapter_id)
        voice_map = self.sm.get_voice_map()

        if not lines:
            print(f"[tts] No pending lines for chapter_id={chapter_id}.")
            self.sm.mark_chapter_status(chapter_id, "tts_done")
            return 0

        ch_dir = self.output_dir / f"ch_{chapter_id:04d}"
        ch_dir.mkdir(parents=True, exist_ok=True)

        total         = len(lines)
        success_count = 0
        print(f"[tts] Synthesising {total} lines for chapter {chapter_id}...")

        for processed, line in enumerate(lines, start=1):
            audio_path = ch_dir / f"line_{line['line_index']:04d}.wav"

            ref_info = self._resolve_ref_audio(
                line["speaker"], line["emotion"], voice_map
            )
            if ref_info is None:
                self.sm.mark_line_failed(
                    line["id"],
                    f"No reference audio for speaker '{line['speaker']}'. "
                    "Register via sm.set_voice() or add a '_default' fallback voice."
                )
                print(f"[tts]   SKIP line {line['line_index']}: no voice for "
                      f"'{line['speaker']}' (tip: register sm.set_voice('_default', path))")
                if progress_callback:
                    progress_callback(processed, total)
                continue

            ref_path, ref_text = ref_info

            using_fallback = (
                f"{line['speaker']}_{line['emotion']}" not in voice_map
                and line["speaker"] not in voice_map
            )

            raw_text       = _normalize_text(line["text"])
            text_with_hint = self._apply_emotion_hint(raw_text, line["emotion"])

            max_chars = self.cfg["max_line_chars"]
            segments  = self._split_long_line(text_with_hint, max_chars)
            if len(segments) > 1:
                print(f"[tts]   SPLIT line {line['line_index']:>4}: "
                      f"{len(segments)} segments ({len(text_with_hint)} chars)")

            wav_bytes = None
            last_err  = None
            for attempt in range(self.cfg["max_retries"] + 1):
                try:
                    if len(segments) == 1:
                        wav_bytes = self._synthesize(segments[0], ref_path, ref_text)
                    else:
                        parts = [self._synthesize(seg, ref_path, ref_text)
                                 for seg in segments]
                        wav_bytes = self._concat_wavs(parts)
                    break
                except Exception as e:
                    last_err  = e
                    err_lower = str(e).lower()
                    is_conn = any(k in err_lower for k in (
                        "connection", "max retries exceeded", "remotedisconnected",
                        "connectionerror", "connectionrefused",
                    ))
                    if is_conn and self._try_restart_server():
                        print(f"[tts]   Retry after server restart "
                              f"(line {line['line_index']})...")
                        time.sleep(2)
                        continue
                    print(f"[tts]   Retry {attempt + 1}/{self.cfg['max_retries']} "
                          f"line {line['line_index']:>4}: {e}")
                    time.sleep(1)

            if wav_bytes:
                audio_path.write_bytes(wav_bytes)
                self.sm.mark_line_tts_done(line["id"], str(audio_path))
                success_count += 1
                fallback_note = " [_default]" if using_fallback else ""
                print(f"[tts]   OK  line {line['line_index']:>4}  [{line['speaker']:<12}] "
                      f"{line['emotion']:<12}{fallback_note} -> {audio_path.name}")
            else:
                self.sm.mark_line_failed(line["id"], str(last_err))
                print(f"[tts]   ERR line {line['line_index']:>4}: {last_err}")

            if progress_callback:
                progress_callback(processed, total)

        self.sm.mark_chapter_status(chapter_id, "tts_done")
        print(f"[tts] Chapter {chapter_id} done: "
              f"{success_count}/{total} lines synthesised.")
        return success_count

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _apply_emotion_hint(text: str, emotion: str) -> str:
        hint = _EMOTION_HINTS.get(emotion, "")
        return hint + text if hint else text

    @staticmethod
    def _split_long_line(text: str, max_chars: int) -> list:
        """Split text at sentence boundaries when it exceeds max_chars."""
        if len(text) <= max_chars:
            return [text]
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, cur = [], ""
        for sent in sentences:
            if cur and len(cur) + 1 + len(sent) <= max_chars:
                cur += " " + sent
            else:
                if cur:
                    chunks.append(cur)
                cur = sent
        if cur:
            chunks.append(cur)
        return chunks or [text]

    @staticmethod
    def _concat_wavs(wav_list: list) -> bytes:
        """Concatenate multiple WAV byte strings into a single WAV."""
        buf = io.BytesIO()
        with _wave_mod.open(buf, "wb") as out:
            for i, raw in enumerate(wav_list):
                with _wave_mod.open(io.BytesIO(raw), "rb") as src:
                    if i == 0:
                        out.setparams(src.getparams())
                    out.writeframes(src.readframes(src.getnframes()))
        return buf.getvalue()

    def _try_restart_server(self) -> bool:
        """Restart the managed Fish Speech server if it has crashed. Returns True if restarted."""
        if not self.managed_server or self._server_proc is None:
            return False
        if self._server_proc.poll() is not None:
            print("[tts]   Server process died — restarting...")
            try:
                self._stop_server()
                self._start_server()
                return True
            except Exception as e:
                print(f"[tts]   Restart failed: {e}")
        return False

    @staticmethod
    def _resolve_ref_audio(
        speaker: str,
        emotion: str,
        voice_map: dict,
    ) -> "tuple[str, str] | None":
        """
        Resolve (ref_audio_path, ref_text) for a speaker + emotion.

        Resolution order:
          1. Normalise raw speaker string (strip + Title Case).
          2. Check SPEAKER_ALIASES → remap to canonical voice key.
          3. Try "{canonical}_{emotion}" in voice_map.
          4. Try "{canonical}" in voice_map.
          5. Try "_default" in voice_map (prints a warning for tracking).
          6. Return None only if _default is also absent (should not happen
             once _default is registered).
        """
        def _extract(entry) -> "tuple[str, str]":
            if isinstance(entry, dict):
                return entry["path"], entry.get("ref_text", "")
            return entry, ""  # backward compat if old string format

        # ── 1. Normalise ──────────────────────────────────────────────────────
        normalised = speaker.strip().title()

        # ── 2. Alias lookup ───────────────────────────────────────────────────
        canonical = SPEAKER_ALIASES.get(normalised, normalised)
        # _default alias target is a sentinel — handle it directly
        if canonical == "_default":
            if "_default" in voice_map:
                print(f"[tts]   ALIAS  '{speaker}' -> _default (NPC/Unknown fallback)")
                return _extract(voice_map["_default"])
            return None

        # ── 3. Emotion-specific override ──────────────────────────────────────
        emotion_key = f"{canonical}_{emotion}"
        if emotion_key in voice_map:
            return _extract(voice_map[emotion_key])

        # ── 4. Base speaker match ─────────────────────────────────────────────
        if canonical in voice_map:
            return _extract(voice_map[canonical])

        # ── 5. _default fallback — print warning for alias tracking ───────────
        if "_default" in voice_map:
            print(
                f"[tts]   WARN   No voice for '{speaker}' "
                f"(normalised: '{normalised}', canonical: '{canonical}') "
                f"— using _default. Add to SPEAKER_ALIASES if recurring."
            )
            return _extract(voice_map["_default"])

        return None

    # ── Raw synthesis call (injectable for testing) ───────────────────────────

    def _synthesize(self, text: str, ref_audio_path: str, ref_text: str = "") -> bytes:
        """
        Call the Fish Speech API and return raw WAV bytes.
        Separated so tests can monkeypatch without a running server.

        ref_text: transcript of the reference audio clip — providing this significantly
                  improves voice cloning accuracy in Fish Speech V1.5.

        Fish Speech /v1/tts contract:
          POST {server_url}/v1/tts
          Body: {
            "text": str,
            "references": [{"audio": <base64_wav>, "text": "<transcript>"}],
            "format": "wav",
            "normalize": true,
            "temperature": float,
            "top_p": float,
            "repetition_penalty": float,
            "max_new_tokens": int,
            "chunk_length": int,
            "streaming": false
          }
          Response: binary WAV content (Content-Type: audio/wav)
                    OR JSON with {"audio": <base64_wav>}
        """
        import requests

        if not ref_text:
            # Fish Speech V1.5 relies on ref_text for phoneme alignment — without it,
            # clone fidelity drops significantly. Register transcripts via
            # sm.set_voice() or the UI "edit transcript" field.
            print(f"[tts]   WARN   ref_text is empty for '{ref_audio_path}' — "
                  "zero-shot quality will be degraded. Add a transcript for this voice.")

        ref_b64 = _encode_audio_b64(ref_audio_path)

        payload = {
            "text":               text,
            "references":         [{"audio": ref_b64, "text": ref_text}],
            "format":             "wav",
            "normalize":          True,
            "streaming":          False,
            "temperature":        self.cfg["temperature"],
            "top_p":              self.cfg["top_p"],
            "repetition_penalty": self.cfg["repetition_penalty"],
            "max_new_tokens":     self.cfg["max_new_tokens"],
            "chunk_length":       self.cfg["chunk_length"],
        }

        resp = requests.post(
            f"{self.server_url}/v1/tts",
            json=payload,
            timeout=self.cfg["request_timeout"],
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "audio" in content_type:
            return resp.content
        # Some versions return JSON with base64 audio
        data = resp.json()
        if "audio" in data:
            return base64.b64decode(data["audio"])
        raise ValueError(f"Unexpected TTS response format: {content_type}\n{resp.text[:200]}")
