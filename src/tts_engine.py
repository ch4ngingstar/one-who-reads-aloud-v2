"""
Module 4: TTS Engine (IndexTTS2)
=================================
Reads diarized lines from the DB, synthesises each line as a WAV file using
**IndexTTS2** zero-shot voice cloning WITH per-line emotional control, and
writes results back.

WHY INDEXTTS2 (vs the previous Fish Speech V1.5):
  Fish was a pure voice cloner — prosody came ONLY from the reference clip, so
  the LLM's per-line `emotion` tag was discarded (flat / robotic output).
  IndexTTS2 has emotion-identity DECOUPLING: a timbre clip (spk_audio_prompt)
  PLUS an independent 8-dim emotion vector (emo_vector) + intensity (emo_alpha).
  We now map every LLM emotion → a vector, so emotion actually drives prosody.

SETUP (one-time):
  1. Clone:   git clone https://github.com/index-tts/index-tts
  2. Install: cd index-tts && pip install -e .
              (Windows: if deepspeed fails to build, run with use_deepspeed=False)
  3. Weights: hf download IndexTeam/IndexTTS-2 --local-dir checkpoints
  4. Point `model_dir` (or the UI "IndexTTS2 Model Dir") at index-tts/checkpoints

VOICE CLONING REFERENCE AUDIO:
  - 5-10 second clean WAV per character (one neutral clip is enough now).
  - Register via StateManager:  sm.set_voice("Sunny", "/voices/sunny.wav")
  - The old "{Speaker}_{emotion}" emotion-clip trick is no longer needed —
    emotion comes from the vector. Such keys still resolve if present.

VRAM LIFECYCLE (Hardware Enforcer):
  IndexTTS2 loads IN-PROCESS (no subprocess server).
  __enter__  -> model loaded into VRAM  (~8 GB)
  __exit__   -> model deleted + CUDA cache emptied -> VRAM released
  LLM must be unloaded BEFORE entering this context (orchestrator enforces it).

  with TTSEngine(sm, output_dir, model_dir="index-tts/checkpoints") as engine:
      engine.process_chapter(chapter_id)
  # <- model freed here, VRAM clear

INPUT  (from Module 2 StateManager):
  sm.get_pending_tts_lines(chapter_id)
  -> [{ "id": int, "line_index": int, "speaker": str, "text": str, "emotion": str }]
  sm.get_voice_map()  -> { "Speaker": {"path": str}, ... }

OUTPUT (to Module 2 StateManager):
  sm.mark_line_tts_done(line_id, audio_path)
  sm.mark_line_failed(line_id, error_message)
  sm.mark_chapter_status(chapter_id, "tts_done")

OUTPUT FILES:
  {output_dir}/ch_{chapter_id:04d}/line_{line_index:04d}.wav
"""

import gc
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Optional


from state_manager import StateManager, _resolve_stored_path
from index25_worker import Index25Worker
from casting import SPEAKER_ALIASES, choose_voice


# ── Emotion → IndexTTS2 vector map ────────────────────────────────────────────
# 8-dim order: [happy, angry, sad, afraid, disgust, melancholic, surprised, calm]
# Each entry is (vector, emo_alpha).  emo_alpha = how strongly the emotion blends
# over the speaker timbre (0 = pure timbre, 1 = full emotion).
# "neutral" maps to an all-zero vector with alpha 0 → pure timbre (no emotion).
# Tune these to taste; they are the dial for the whole audiobook's expressiveness.
# emo_alpha is capped at ~0.7. IndexTTS2 grows unstable / mechanical-sounding
# when a single-emotion vector is blended at very high alpha (0.85-1.0) — it is
# pushed out of the timbre distribution it was conditioned on. 0.45-0.70 keeps
# the emotion clearly audible while preserving natural prosody. Adjust the whole
# audiobook's expressiveness globally via cfg["emo_alpha_scale"].
INDEXTTS2_EMOTION_VECTORS: dict[str, "tuple[list[float], float]"] = {
    #            [hap, ang, sad, afr, dis, mel, sur, calm]
    "neutral":   ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0.0),
    # Weak-4 retune (CANDIDATE — pending ear). eval_emotion flagged whispers/cold/
    # sad/pleading as "barely distinct" from neutral (f0 lift only +6..+11 Hz), and
    # whispers read *louder* than neutral (rms_rel +0.09) — wrong for a whisper.
    # 2026-06-21 GPU re-probe (Sunny ref, vs forced-neutral):
    #   whispers OK  — now ΔF0 -2 Hz, rms_rel -0.26 (quieter/breathier, the fix).
    #   cold     OK  — ΔF0 +17 Hz, harder edge, loudness unchanged.
    #   sad/pleading OVERSHOT on the first weak-4 vectors (sad ΔF0 +40 Hz & LOUDER;
    #   pleading ΔF0 +88 Hz ≈ 211 Hz, ~2× loud — near-falsetto risk). The `afraid`
    #   dim drives pitch up hard, so sad/pleading were MODERATED below (lower
    #   afraid + emo_alpha) toward plaintive-not-shrieky. See eval-report.
    "whispers":  ([0.0, 0.0, 0.3, 0.15, 0.0, 0.4, 0.0, 0.15], 0.40),
    # Retuned 2026-06-20 (hot-5 pass): lowered emo_alpha + added a calm anchor on
    # the 5 "hot" tags whose objective f0 lift hit +94..+135 Hz (Sunny neutral
    # ~125 Hz → near falsetto 220-260 Hz). Approved by ear. See eval-report.
    "angry":     ([0.0, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.2], 0.45),
    "sad":       ([0.0, 0.0, 0.9, 0.0, 0.0, 0.4, 0.0, 0.0], 0.60),  # moderated from 1.0/0.5@0.75
    "excited":   ([0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.1], 0.45),
    "commanding":([0.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6], 0.60),
    "frightened":([0.0, 0.0, 0.0, 0.7, 0.0, 0.0, 0.15, 0.15], 0.50),
    "confused":  ([0.0, 0.0, 0.0, 0.2, 0.0, 0.2, 0.5, 0.0], 0.55),
    "pleading":  ([0.0, 0.0, 0.6, 0.4, 0.0, 0.1, 0.0, 0.0], 0.60),  # afraid 0.4/a0.60: target ~+40Hz (0.3@.55=+3, 0.5@.72=+88)
    "cold":      ([0.0, 0.25, 0.0, 0.0, 0.2, 0.1, 0.0, 0.55], 0.50),
    "laughing":  ([0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.05], 0.45),
    "sarcastic": ([0.3, 0.2, 0.0, 0.0, 0.3, 0.0, 0.0, 0.3], 0.55),
    "desperate": ([0.0, 0.0, 0.45, 0.45, 0.0, 0.2, 0.0, 0.1], 0.50),
}


# ── Default IndexTTS2 config ──────────────────────────────────────────────────
_DEFAULT_CFG = {
    # use_fp16=False (full precision) measurably improves naturalness — half
    # precision added a subtle "robotic" edge in A/B testing. The RTX 4070 still
    # fits IndexTTS2 in fp32 since the LLM is never co-resident.
    "use_fp16":       False,
    "use_deepspeed":  False,   # deepspeed often fails to build on Windows; off by default
    "use_cuda_kernel": False,  # BigVGAN custom CUDA kernel — off for portability
    "max_retries":    2,       # retries on a failed generation
    "max_line_chars": 400,     # lines longer than this are split at sentence boundaries
    "emo_alpha_scale": 1.0,    # global multiplier on per-emotion alpha (master dial)
    # Narration is description, not performance. Even when the diarizer assigns a
    # charged tag to Narrator prose (horror/battle passages), full-intensity
    # emotion makes the narrator over-act and read too loud (ch_1854 ~3:46 was
    # frightened narration). Scale the Narrator's emo_alpha down so it stays
    # measured; character dialogue is unaffected. 0.0 = always-neutral narration.
    # 0.3 chosen by ear from a 1.0/0.5/0.3/0.0 A/B on the ch_1854 frightened line.
    "narrator_emo_scale": 0.3,
    "config_name":    "config.yaml",  # IndexTTS2 config filename inside model_dir
    # GPT sampling — tuned for smoother long-form narration. Larger segments mean
    # fewer prosody seams (IndexTTS2 default 120 chops mid-sentence).
    # num_beams=1 (greedy): A/B testing showed beam search is the dominant cost
    # here (~10× slower per line) AND flattens emotional prosody — beam search
    # optimises for the most-probable sequence, which averages out expressive
    # delivery. Greedy is faster, lower-VRAM, and more dynamic on emotional lines.
    # Passed straight to IndexTTS2.infer().
    "max_text_tokens_per_segment": 200,
    "num_beams":      1,
    "db_flush_every": 1,    # checkpoint every expensive GPU inference
}


from spoken_text import normalize_text as _normalize_text, split_for_speech


from speech_audio import concat_wavs, wav_silence as _wav_silence


class TTSEngine:
    """
    VRAM-safe TTS engine backed by IndexTTS2.  Must be used as a context manager.

    Parameters
    ----------
    state_manager : StateManager instance.
    output_dir    : Root dir for WAV output files.
    model_dir     : Path to the IndexTTS2 `checkpoints/` directory (config.yaml +
                    weights). Required to actually load the model (not needed for
                    tests that monkeypatch `_synthesize`).
    cfg           : Optional dict overriding _DEFAULT_CFG values.

    Back-compat: the old Fish-era kwargs (`fish_speech_dir`, `server_url`,
    `managed_server`) are accepted and ignored so existing callers don't break.
    """

    def __init__(
        self,
        state_manager: StateManager,
        output_dir: "str | Path",
        model_dir: "str | Path | None" = None,
        cfg: "dict | None" = None,
        # Ignored Fish-era back-compat kwargs:
        fish_speech_dir: "str | Path | None" = None,
        server_url: "str | None" = None,
        managed_server: "bool | None" = None,
    ):
        self.sm         = state_manager
        self.output_dir = Path(output_dir)
        # Allow the legacy fish_speech_dir slot to carry the model dir if model_dir
        # was not explicitly provided (keeps old orchestrator wiring functional).
        _md = model_dir if model_dir is not None else fish_speech_dir
        self.model_dir  = Path(_md) if _md else None
        self.cfg        = {**_DEFAULT_CFG, **(cfg or {})}
        self.model = None  # loaded in __enter__

    # ── Context manager (Hardware Enforcer) ───────────────────────────────────

    def __enter__(self):
        self._load_model()
        print("[tts] Speech engine ready.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Free the model and reclaim VRAM.
        if isinstance(self.model, Index25Worker):
            self.model.close()
        self.model = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            print("[tts] CUDA cache cleared.")
        except ImportError:
            pass
        print("[tts] VRAM released.")
        return False

    # ── Model lifecycle ───────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if self.model_dir is None:
            raise ValueError(
                "model_dir must be set to the IndexTTS2 checkpoints directory.\n"
                "Clone: git clone https://github.com/index-tts/index-tts\n"
                "Weights: hf download IndexTeam/IndexTTS-2 --local-dir checkpoints"
            )
        model_dir = _resolve_stored_path(self.model_dir).resolve()
        cfg_path = model_dir / self.cfg["config_name"]
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"IndexTTS2 config not found: {cfg_path}. "
                "Point model_dir at the checkpoints dir containing config.yaml."
            )
        import yaml
        version = str(yaml.safe_load(cfg_path.read_text(encoding="utf-8")).get("version", "2.0"))
        if version == "2.5":
            self.model = Index25Worker(model_dir)
            return
        if version not in {"2", "2.0"}:
            raise ValueError(f"Unsupported IndexTTS checkpoint version {version} in {cfg_path}")
        # Tell HuggingFace to use the local cache only — no network checks.
        # infer_v2 calls hf_hub_download / from_pretrained for w2v-bert-2.0,
        # amphion/MaskGCT, and funasr/campplus; these succeed from cache but
        # fail silently on first-time use without internet.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from indextts.infer_v2 import IndexTTS2
        except ImportError as e:
            raise RuntimeError(
                "IndexTTS2 is not installed. Install it from source:\n"
                "  git clone https://github.com/index-tts/index-tts\n"
                "  cd index-tts && pip install -e ."
            ) from e

        print(f"[tts] Loading IndexTTS2 from {model_dir} "
              f"(fp16={self.cfg['use_fp16']}, deepspeed={self.cfg['use_deepspeed']})...")
        self.model = IndexTTS2(
            cfg_path=str(cfg_path),
            model_dir=str(model_dir),
            use_fp16=self.cfg["use_fp16"],
            use_deepspeed=self.cfg["use_deepspeed"],
            use_cuda_kernel=self.cfg["use_cuda_kernel"],
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def process_chapter(
        self,
        chapter_id: int,
        progress_callback: "Callable[[int, int, dict], None] | None" = None,
    ) -> int:
        """
        Synthesise all pending lines for a chapter.
        Returns the count of successfully generated lines.
        Advances chapter status to 'tts_done'.

        progress_callback(lines_processed, lines_total, line) is called after
        every line; `line` is the just-processed line dict (text/speaker/emotion)
        so callers can surface the live line in progress events.
        """
        lines     = self.sm.get_pending_tts_lines(chapter_id)
        voice_map = self.sm.get_voice_map()
        readings = {name.casefold(): reading for name, reading in self.sm.get_pronunciations().items()}
        pronunciations = None
        if readings:
            alternatives = "|".join(re.escape(word) for word in sorted(readings, key=len, reverse=True))
            pronunciations = re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)", re.IGNORECASE)

        if not lines:
            print(f"[tts] No pending lines for chapter_id={chapter_id}.")
            if self.sm.get_line_progress(chapter_id)["total"] == 0:
                raise ValueError(f"Chapter {chapter_id} has no labelled lines to synthesize.")
            self.sm.mark_chapter_status(chapter_id, "tts_done")
            return 0

        ch_dir = self.output_dir / f"ch_{chapter_id:04d}"
        ch_dir.mkdir(parents=True, exist_ok=True)

        total         = len(lines)
        success_count = 0
        _pending_db: list[tuple[int, str]] = []
        print(f"[tts] Synthesising {total} lines for chapter {chapter_id}...")

        for processed, line in enumerate(lines, start=1):
            audio_path = ch_dir / f"line_{line['line_index']:04d}.wav"

            choice = choose_voice(line["speaker"], line["emotion"], voice_map)
            ref_path = choice.path
            if ref_path is None:
                # Only reachable when NO voices are registered at all — a hard
                # config error, not a per-line skip. _resolve_ref_audio always
                # returns a real voice for any mapped/unmapped speaker otherwise.
                self.sm.mark_line_failed(
                    line["id"],
                    "No voices registered at all — cannot synthesise. "
                    "Register at least one voice (e.g. sm.set_voice('_default', path))."
                )
                print(f"[tts]   ERR line {line['line_index']}: no voices registered "
                      "(config error, not a per-line skip)")
                if progress_callback:
                    progress_callback(processed, total, line)
                continue

            spoken_text = line["text"]
            if pronunciations:
                spoken_text = pronunciations.sub(lambda m: readings.get(m[0].casefold(), m[0]), spoken_text)
            raw_text              = _normalize_text(spoken_text)
            emo_vector, emo_alpha = self._resolve_emotion(line["emotion"])
            emo_alpha            *= self.cfg["emo_alpha_scale"]
            # Keep narration measured — damp the narrator's emotional intensity so
            # charged prose (e.g. frightened horror description) never over-acts.
            if choice.canonical == "Narrator":
                emo_alpha *= self.cfg["narrator_emo_scale"]

            max_chars = self.cfg["max_line_chars"]
            segments  = self._split_long_line(raw_text, max_chars)
            if len(segments) > 1:
                print(f"[tts]   SPLIT line {line['line_index']:>4}: "
                      f"{len(segments)} segments ({len(raw_text)} chars)")

            try:
                parts = [self._render_segment(segment, ref_path, emo_vector, emo_alpha)
                         for segment in segments]
                wav_bytes = parts[0] if len(parts) == 1 else self._concat_wavs(parts)
            except Exception as exc:
                wav_bytes = None
                error = f"{line['speaker']} (line {line['line_index']}): {exc}"
                self.sm.mark_line_failed(line["id"], error)
                print(f"[tts]   ERR {error}")

            if wav_bytes:
                stage_path = None
                try:
                    with tempfile.NamedTemporaryFile(dir=ch_dir, suffix=".part", delete=False) as tmp:
                        stage_path = Path(tmp.name)
                        tmp.write(wav_bytes)
                    stage_path.replace(audio_path)
                finally:
                    if stage_path:
                        stage_path.unlink(missing_ok=True)
                _pending_db.append((line["id"], str(audio_path)))
                success_count += 1
                if len(_pending_db) >= self.cfg["db_flush_every"]:
                    self.sm.mark_lines_tts_done(_pending_db)
                    _pending_db.clear()
                fallback_note = " [_default]" if choice.fallback else ""
                print(f"[tts]   OK  line {line['line_index']:>4}  [{line['speaker']:<12}] "
                      f"{line['emotion']:<12}{fallback_note} -> {audio_path.name}")
            if progress_callback:
                progress_callback(processed, total, line)

        if _pending_db:
            self.sm.mark_lines_tts_done(_pending_db)
            _pending_db.clear()

        if success_count < total:
            message = f"{total - success_count}/{total} lines failed. Start again to retry those lines."
            self.sm.mark_chapter_status(chapter_id, "error", error_message=f"[failed_stage:synthesize] {message}")
            return success_count
        self.sm.mark_chapter_status(chapter_id, "tts_done")
        print(f"[tts] Chapter {chapter_id} done: "
              f"{success_count}/{total} lines synthesised.")
        return success_count

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_emotion(emotion: str) -> "tuple[list[float] | None, float]":
        """
        Map an LLM emotion string → (emo_vector, emo_alpha) for IndexTTS2.
        Unknown emotions and 'neutral' return (None, 0.0) → pure speaker timbre.
        """
        vec, alpha = INDEXTTS2_EMOTION_VECTORS.get(emotion, (None, 0.0))
        if vec is None or not any(v > 0.0 for v in vec):
            return None, 0.0
        return vec, alpha

    _split_long_line = staticmethod(split_for_speech)

    _concat_wavs = staticmethod(concat_wavs)

    def _render_segment(self, text, ref_path, emo_vector, emo_alpha) -> bytes:
        if not any(char.isalnum() for char in text):
            return _wav_silence(250)
        # Retry only the bad segment, always using the selected character.
        attempts = max(1, int(self.cfg["max_retries"]) + 1)
        for attempt in range(1, attempts + 1):
            try:
                audio = self._synthesize(text, ref_path, emo_vector, emo_alpha)
                if not audio:
                    raise ValueError("Renderer returned no audio")
                return audio
            except Exception as exc:
                if attempt == attempts:
                    raise
                print(f"[tts]   Repeating segment after attempt {attempt}/{attempts}: {exc}")

    @staticmethod
    def _resolve_ref_audio(speaker: str, emotion: str, voice_map: dict) -> "str | None":
        return choose_voice(speaker, emotion, voice_map).path

    # ── Raw synthesis call (injectable for testing) ───────────────────────────

    def _synthesize(
        self,
        text: str,
        ref_audio_path: str,
        emo_vector: "list[float] | None" = None,
        emo_alpha: float = 0.0,
    ) -> bytes:
        """
        Call IndexTTS2 and return raw WAV bytes.
        Separated so tests can monkeypatch without a loaded model.

        ref_audio_path : the speaker timbre clip (spk_audio_prompt).
        emo_vector     : 8-dim emotion vector, or None for pure timbre.
        emo_alpha      : emotion blend strength (0..1).
        """
        if self.model is None:
            raise RuntimeError(
                "IndexTTS2 model not loaded — use TTSEngine as a context manager "
                "(`with TTSEngine(...) as engine:`)."
            )

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            infer_kwargs = dict(
                spk_audio_prompt=str(_resolve_stored_path(ref_audio_path)),
                text=text,
                output_path=tmp.name,
                verbose=False,
                max_text_tokens_per_segment=self.cfg["max_text_tokens_per_segment"],
                num_beams=self.cfg["num_beams"],
            )
            if emo_vector is not None:
                infer_kwargs["emo_vector"] = emo_vector
                infer_kwargs["emo_alpha"] = emo_alpha

            self.model.infer(**infer_kwargs)

            from speech_audio import check_utterance
            audio = Path(tmp.name).read_bytes()
            check_utterance(audio, text)
            return audio
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
