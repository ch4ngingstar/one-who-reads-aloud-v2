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
import io
import os
import re
import tempfile
import wave as _wave_mod
from pathlib import Path
from typing import Callable, Optional


from state_manager import StateManager


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

    # Post-Vol-9 character title variants (canonical names added to DEFAULT_SPEAKERS).
    "Saint Jest":         "Jest",

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
    "db_flush_every": 10,   # write tts_done updates to DB every N lines (resume granularity)
}


# Non-speech stage directions the LLM occasionally emits inside asterisks.
# These are deleted; any other *emphasised* text keeps its content.
_STAGE_DIRECTION_RE = re.compile(
    r'\*(?:sighs?|pauses?|laughs?|chuckles?|giggles?|groans?|grunts?|gasps?|'
    r'coughs?|snorts?|scoffs?|hums?|exhales?|inhales?|sniffs?|sobs?|'
    r'clears throat|beat|silence)\*',
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    """
    Clean up text for maximum TTS accuracy.
    Fixes Unicode typography, normalises whitespace, and handles
    common novel formatting that confuses speech synthesisers.
    """
    # Unicode quotes → ASCII
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    # Strip italic/emphasis markers but keep their content. Only a known
    # vocabulary of LLM stage directions is removed outright — a generic
    # "any lowercase word" rule would delete legitimately emphasised words
    # like *enormous* from the narration.
    text = _STAGE_DIRECTION_RE.sub('', text)                  # *sighs* → gone
    text = re.sub(r'\*([^*]{1,120})\*', r'\1', text)          # *inner thought* → inner thought
    # Strip square brackets but KEEP their content (e.g. [Aspect of the Void]).
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)
    # Em-dash handling: mid-word interruption → ellipsis; mid-sentence → comma
    text = re.sub(r'(\w)—$', r'\1...', text)
    text = re.sub(r'(\w)—(\w)', r'\1, \2', text)
    text = text.replace('—', ', ')
    # En-dash → spaced hyphen
    text = text.replace('–', ' - ')
    # Horizontal ellipsis → three dots
    text = text.replace('…', '...')
    # Non-breaking space → regular space
    text = text.replace(' ', ' ')
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
    text = re.sub(r'[,;]\s*$', '.', text)
    text = re.sub(r'(\w)$', lambda m: m.group(1) + '.', text)
    return text.strip()


def _wav_silence(duration_ms: int = 100, sample_rate: int = 22050) -> bytes:
    """Generate a minimal silent WAV file as a fallback placeholder."""
    import struct
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
        print("[tts] IndexTTS2 engine ready.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Free the model and reclaim VRAM.
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
        model_dir = self.model_dir.resolve()
        cfg_path = model_dir / self.cfg["config_name"]
        if not cfg_path.exists():
            raise FileNotFoundError(
                f"IndexTTS2 config not found: {cfg_path}. "
                "Point model_dir at the checkpoints dir containing config.yaml."
            )
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

        if not lines:
            print(f"[tts] No pending lines for chapter_id={chapter_id}.")
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

            ref_path = self._resolve_ref_audio(
                line["speaker"], line["emotion"], voice_map
            )
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

            # Note when the line landed on the _default voice (uses the same
            # alias normalisation as _resolve_ref_audio so the flag is accurate).
            _norm      = line["speaker"].strip().title()
            _canonical = SPEAKER_ALIASES.get(_norm, _norm)
            using_fallback = (
                f"{_canonical}_{line['emotion']}" not in voice_map
                and _canonical not in voice_map
            )

            raw_text              = _normalize_text(line["text"])
            emo_vector, emo_alpha = self._resolve_emotion(line["emotion"])
            emo_alpha            *= self.cfg["emo_alpha_scale"]

            max_chars = self.cfg["max_line_chars"]
            segments  = self._split_long_line(raw_text, max_chars)
            if len(segments) > 1:
                print(f"[tts]   SPLIT line {line['line_index']:>4}: "
                      f"{len(segments)} segments ({len(raw_text)} chars)")

            # Try the resolved voice; if every retry fails, fall back to a
            # guaranteed voice so a corrupt/odd ref clip can never drop a line.
            # A line only ends up failed if the engine itself fails on BOTH
            # voices (e.g. OOM/crash) — never for a content/mapping reason.
            fallback_path  = self._fallback_ref(voice_map)
            ref_candidates = [ref_path]
            if fallback_path and fallback_path != ref_path:
                ref_candidates.append(fallback_path)

            wav_bytes = None
            last_err  = None
            for cand_idx, cand_ref in enumerate(ref_candidates):
                for attempt in range(self.cfg["max_retries"] + 1):
                    try:
                        if len(segments) == 1:
                            wav_bytes = self._synthesize(
                                segments[0], cand_ref, emo_vector, emo_alpha
                            )
                        else:
                            parts = [
                                self._synthesize(seg, cand_ref, emo_vector, emo_alpha)
                                for seg in segments
                            ]
                            wav_bytes = self._concat_wavs(parts)
                        break
                    except Exception as e:
                        last_err = e
                        print(f"[tts]   Retry {attempt + 1}/{self.cfg['max_retries']} "
                              f"line {line['line_index']:>4}: {e}")
                if wav_bytes:
                    if cand_idx > 0:
                        print(f"[tts]   FALLBACK line {line['line_index']:>4}: "
                              "resolved voice failed all retries, "
                              "synthesised on fallback voice")
                    break

            if wav_bytes:
                audio_path.write_bytes(wav_bytes)
                _pending_db.append((line["id"], str(audio_path)))
                success_count += 1
                if len(_pending_db) >= self.cfg["db_flush_every"]:
                    self.sm.mark_lines_tts_done(_pending_db)
                    _pending_db.clear()
                fallback_note = " [_default]" if using_fallback else ""
                print(f"[tts]   OK  line {line['line_index']:>4}  [{line['speaker']:<12}] "
                      f"{line['emotion']:<12}{fallback_note} -> {audio_path.name}")
            else:
                self.sm.mark_line_failed(line["id"], str(last_err))
                print(f"[tts]   ERR line {line['line_index']:>4}: {last_err}")

            if progress_callback:
                progress_callback(processed, total, line)

        if _pending_db:
            self.sm.mark_lines_tts_done(_pending_db)
            _pending_db.clear()

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

    @staticmethod
    def _split_long_line(text: str, max_chars: int) -> list:
        """Split text at sentence boundaries when it exceeds max_chars.
        A single sentence longer than max_chars is hard-split at the last
        comma (or space) before the limit so no segment can overflow."""
        if len(text) <= max_chars:
            return [text]

        def hard_split(sent: str) -> list:
            parts = []
            while len(sent) > max_chars:
                cut = sent.rfind(',', max_chars // 2, max_chars)
                if cut != -1:
                    head, sent = sent[:cut + 1], sent[cut + 1:]   # keep the comma
                else:
                    cut = sent.rfind(' ', max_chars // 2, max_chars)
                    if cut != -1:
                        head, sent = sent[:cut], sent[cut + 1:]
                    else:
                        head, sent = sent[:max_chars], sent[max_chars:]
                parts.append(head.strip())
                sent = sent.strip()
            if sent:
                parts.append(sent)
            return parts

        units: list = []
        for sent in re.split(r'(?<=[.!?])\s+', text):
            if len(sent) > max_chars:
                units.extend(hard_split(sent))
            else:
                units.append(sent)

        chunks, cur = [], ""
        for unit in units:
            if cur and len(cur) + 1 + len(unit) <= max_chars:
                cur += " " + unit
            else:
                if cur:
                    chunks.append(cur)
                cur = unit
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

    @staticmethod
    def _extract_path(entry) -> str:
        """Voice-map entries are {'path':..,'ref_text':..} dicts (or bare path
        strings in the legacy format). Return the path either way."""
        if isinstance(entry, dict):
            return entry["path"]
        return entry

    @staticmethod
    def _fallback_ref(voice_map: dict) -> "str | None":
        """Guaranteed non-skip fallback chain so a line is NEVER dropped for lack
        of a mapped voice: _default → Narrator → any registered voice (chosen
        deterministically by sorting). Returns None ONLY when voice_map is empty —
        a true config error (no voices registered at all)."""
        for key in ("_default", "Narrator"):
            if key in voice_map:
                return TTSEngine._extract_path(voice_map[key])
        for key in sorted(voice_map):
            return TTSEngine._extract_path(voice_map[key])
        return None

    @staticmethod
    def _resolve_ref_audio(
        speaker: str,
        emotion: str,
        voice_map: dict,
    ) -> "str | None":
        """
        Resolve the ref_audio_path for a speaker + emotion.

        Resolution order:
          1. Normalise raw speaker string (strip + Title Case).
          2. Check SPEAKER_ALIASES → remap to canonical voice key.
          3. Try "{canonical}_{emotion}" in voice_map (legacy emotion clips).
          4. Try "{canonical}" in voice_map.
          5. Fall back via _fallback_ref (_default → Narrator → any voice).

        A line is NEVER skipped for a missing mapping — unmapped speakers always
        land on a real voice. None is returned ONLY when no voices are registered
        at all (voice_map empty), which the caller treats as a hard config error.
        """
        normalised = speaker.strip().title()
        canonical = SPEAKER_ALIASES.get(normalised, normalised)

        if canonical != "_default":
            emotion_key = f"{canonical}_{emotion}"
            if emotion_key in voice_map:
                return TTSEngine._extract_path(voice_map[emotion_key])
            if canonical in voice_map:
                return TTSEngine._extract_path(voice_map[canonical])
            print(
                f"[tts]   WARN   No voice for '{speaker}' "
                f"(normalised: '{normalised}', canonical: '{canonical}') "
                f"— using fallback voice. Add to SPEAKER_ALIASES if recurring."
            )
        else:
            print(f"[tts]   ALIAS  '{speaker}' → fallback voice (NPC/Unknown)")

        return TTSEngine._fallback_ref(voice_map)

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
                spk_audio_prompt=ref_audio_path,
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

            with open(tmp.name, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
