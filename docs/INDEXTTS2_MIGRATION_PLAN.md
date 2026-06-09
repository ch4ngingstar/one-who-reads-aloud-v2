# IndexTTS2 Migration Plan — replacing Fish Speech V1.5

**Status:** CODE COMPLETE (Phases 1-4, 6, 7 done; all tests green:
64 Python + 12 UI + typecheck). Remaining: **Phase 8** = user installs IndexTTS2
+ weights and points `tts_model_dir` at `index-tts/checkpoints` (see bottom).
**Phase 5** (two-pass batching) intentionally deferred — optional perf.

Verified green: `python tests/test_tts_engine.py` (31), `test_orchestrator.py`
(14), `test_api.py` (19), `cd ui && npm test` (12), `npm run typecheck` (clean).
**Goal:** Replace Fish Speech V1.5 with **IndexTTS2** as the TTS backend so the
LLM's per-line `emotion` tags actually drive prosody (Fish ignored them — that was
the root cause of the flat/robotic voice). Target HW: **RTX 4070 (12 GB)**, Windows.

This file is the source of truth for the migration. If the session is interrupted,
resume from the first unchecked box. Each phase is independently testable.

---

## Why IndexTTS2 (decision record)

- Fish V1.5 is a *pure voice cloner* — prosody comes ONLY from the reference clip.
  `_EMOTION_HINTS` was intentionally empty; emotion was faked by hunting for a
  `{speaker}_{emotion}` clip that almost never existed → flat output.
- IndexTTS2 has **emotion–identity decoupling**: a timbre clip (`spk_audio_prompt`)
  + an independent **8-dim emotion vector** (`emo_vector`) and intensity (`emo_alpha`).
  This maps 1:1 onto our existing `(speaker, emotion)` per-line output.
- Lowest WER of 2026 models (matters over 422 chapters). Fits 12 GB (~8 GB).
- **Trade-off accepted:** IndexTTS2 is autoregressive → slower than Fish
  (RTF ~0.5–1.5 optimized vs Fish ~0.2). For a 422-ch novel this is the cost of
  real emotion. Mitigated by Phase 5 (two-pass batching) later.
- License: research/non-commercial-leaning. Fine for personal use; do NOT
  redistribute generated models.

---

## Architecture change summary

- TTS no longer runs as an HTTP **subprocess server** (Fish's `api_server.py`).
  IndexTTS2 loads **in-process** inside the `__enter__`/`__exit__` context manager,
  same VRAM-lifecycle guarantee (model freed on `__exit__` →
  `del model; gc.collect(); torch.cuda.empty_cache()`). The orchestrator's VRAM
  barrier (LLM→TTS) is unchanged and still enforced.
- Emotion is now consumed: each LLM emotion string → an 8-dim `emo_vector` +
  `emo_alpha`, passed per line to `IndexTTS2.infer()`.
- `{speaker}_{emotion}` reference clips are no longer needed (resolution still
  falls back to base speaker). One clean neutral clip per character is enough.
- Config/field rename: `fish_speech_dir` → `tts_model_dir` (the IndexTTS2
  `checkpoints/` dir). Backward-compatible: API/UI still accept the old key.

### Emotion → IndexTTS2 vector map
8-dim order = **[happy, angry, sad, afraid, disgust, melancholic, surprised, calm]**.
LLM `EMOTION_VOCAB` = neutral, whispers, angry, sad, excited, commanding,
frightened, confused, pleading, cold, laughing, sarcastic, desperate.

| emotion     | vector [hap,ang,sad,afr,dis,mel,sur,calm]      | alpha |
|-------------|------------------------------------------------|-------|
| neutral     | [0,0,0,0,0,0,0,0]                               | 0.0   |
| whispers    | [0,0,0.1,0,0,0.2,0,0.6]                         | 0.5   |
| angry       | [0,1.0,0,0,0,0,0,0]                             | 0.85  |
| sad         | [0,0,0.9,0,0,0.3,0,0]                           | 0.85  |
| excited     | [0.8,0,0,0,0,0,0.4,0]                           | 0.85  |
| commanding  | [0,0.3,0,0,0,0,0,0.6]                           | 0.7   |
| frightened  | [0,0,0,1.0,0,0,0.2,0]                           | 0.9   |
| confused    | [0,0,0,0.2,0,0.2,0.5,0]                         | 0.7   |
| pleading    | [0,0,0.6,0.3,0,0,0,0]                           | 0.8   |
| cold        | [0,0.15,0,0,0.1,0.1,0,0.6]                      | 0.5   |
| laughing    | [1.0,0,0,0,0,0,0.3,0]                           | 0.85  |
| sarcastic   | [0.3,0.2,0,0,0.3,0,0,0.3]                       | 0.7   |
| desperate   | [0,0,0.5,0.6,0,0.2,0,0]                         | 0.9   |

(Tunable later. neutral = pure timbre, alpha 0.)

---

## Phases / checklist

### Phase 0 — Plan saved
- [x] Write this plan to `docs/INDEXTTS2_MIGRATION_PLAN.md`

### Phase 1 — Core engine rewrite (`src/tts_engine.py`)
- [ ] New `INDEXTTS2_EMOTION_VECTORS` dict (table above).
- [ ] `TTSEngine` (keep class name for drop-in compat) loads IndexTTS2 in `__enter__`,
      frees it in `__exit__`. Constructor: `model_dir` (checkpoints), `cfg`, drop
      `fish_speech_dir`/`server_url`/`managed_server` (keep as ignored kwargs for
      back-compat so orchestrator/tests don't explode).
- [ ] Keep static helpers used by tests: `_resolve_ref_audio`, `_split_long_line`,
      `_concat_wavs`, `_normalize_text`, `_wav_silence`.
- [ ] New `_synthesize(text, ref_audio_path, ref_text="", emo_vector=None, emo_alpha=0.0)`
      → WAV bytes (writes IndexTTS2 output to temp, reads bytes). Still injectable.
- [ ] `process_chapter` resolves emotion → (vector, alpha) and passes to `_synthesize`.
- [ ] Replace `_apply_emotion_hint` usage; emotion now flows via vector not text.
- [ ] Keep `SPEAKER_ALIASES` and `_resolve_ref_audio` exactly (still needed).

### Phase 2 — Orchestrator + config (`src/orchestrator.py`)
- [ ] `PipelineConfig`: rename `fish_speech_dir`→`tts_model_dir`,
      `fish_speech_url`→drop, `managed_tts_server`→drop (or keep ignored).
- [ ] `_stage_synthesize` constructs engine with `model_dir=self.cfg.tts_model_dir`.

### Phase 3 — API (`src/api.py`)
- [ ] `ProjectCreate`/`PipelineStart`: add `tts_model_dir`, keep `fish_speech_dir`
      as deprecated alias (use whichever is provided).
- [ ] Pass through to `PipelineConfig.tts_model_dir`.

### Phase 4 — UI (`ui/`)
- [ ] `ProjectSetup.tsx`: relabel "Fish Speech Directory" → "IndexTTS2 Model Dir"
      (`tts_model_dir`), placeholder `checkpoints` or `index-tts/checkpoints`.
- [ ] `page.tsx`: `fishDir`→`ttsModelDir`; localStorage key migrate (read old `fishDir`).
- [ ] `lib/api.ts`: field rename + alias.
- [ ] Copy tweaks ("Fish Speech directory" text on the empty-state hint).

### Phase 5 — Two-pass batching (OPTIONAL perf, can defer)
- [ ] Add orchestrator mode: diarize ALL chapters (LLM resident), then synth ALL
      (TTS resident). Eliminates per-chapter model reloads. Behind a config flag,
      default off to preserve resume semantics initially.

### Phase 6 — Deps + docs
- [ ] `requirements.txt`: drop Fish note; add IndexTTS2 install instructions
      (it's a git install, not pip — document, don't pin).
- [ ] Update `CLAUDE.md` External dependencies + VRAM section + voice resolution.
- [ ] `scripts/run_chapters.py`: `FISH`→`TTS_MODEL_DIR`.

### Phase 7 — Tests green
- [ ] Rewrite `tests/test_tts_engine.py` for IndexTTS2 (mock `_synthesize` with new
      sig incl. `emo_vector`/`emo_alpha`; add emotion-vector resolution tests;
      drop Fish-only `_EMOTION_HINTS`/emotion-clip tests).
- [ ] `tests/test_orchestrator.py`: update field name `fish_speech_dir`→`tts_model_dir`.
- [ ] `tests/test_api.py`: update payloads.
- [ ] `ui/tests/ChapterGrid.test.tsx`: copy string "Fish Speech crashed" is just
      sample error text — leave or relabel.
- [ ] Run: `python tests/test_tts_engine.py`, `test_orchestrator.py`, `test_api.py`,
      `cd ui && npm test && npm run typecheck`.

### Phase 8 — Real install (USER action, documented)
- IndexTTS2 is NOT pip-installable cleanly. Steps to document:
  ```
  git clone https://github.com/index-tts/index-tts
  cd index-tts
  pip install -e .            # or: uv sync --all-extras  (deepspeed may fail on Win)
  # weights:
  hf download IndexTeam/IndexTTS-2 --local-dir checkpoints
  ```
  - Windows: if `deepspeed` build fails, install with deepspeed disabled
    (`USE_DEEPSPEED=0` / set `use_deepspeed=False` in engine) — IndexTTS2 runs
    without it, just a bit slower.
- Point UI "IndexTTS2 Model Dir" at `index-tts/checkpoints`.

---

## Files touched
- `src/tts_engine.py` (rewrite)         — Phase 1
- `src/orchestrator.py`                  — Phase 2
- `src/api.py`                           — Phase 3
- `ui/components/ProjectSetup.tsx`       — Phase 4
- `ui/app/page.tsx`                      — Phase 4
- `ui/lib/api.ts`                        — Phase 4
- `requirements.txt`                     — Phase 6
- `CLAUDE.md`                            — Phase 6
- `scripts/run_chapters.py`              — Phase 6
- `tests/test_tts_engine.py` (rewrite)   — Phase 7
- `tests/test_orchestrator.py`           — Phase 7
- `tests/test_api.py`                    — Phase 7

## Rollback
Fish engine is preserved in git history (commit before this work). The engine
constructor keeps ignored back-compat kwargs so reverting only `tts_engine.py`
restores Fish behavior if needed.
