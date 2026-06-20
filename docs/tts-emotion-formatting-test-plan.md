# TTS Emotion, Accuracy & Formatting Test Plan

> Status: DRAFT — written 2026-06-20. Defaults chosen by Claude per "save for later and be fast".
> Scope decisions baked in (recommended forks): **Hybrid** measurement (objective scripts + human A/B),
> **Test → recommend → implement** (gated on results), **Cloud-LLM reference gold set** (reuse `diarization_io`),
> **EPUB-derived roster audit** for post-Volume-9 Shadow Slave content.

## Context — why this exists

You asked: *test how the per-line emotion vectors actually affect the output voices, how accurate the TTS
is, how the formatting (segmentation + diarization) is doing, and what formatting gives the best pipeline
output — while keeping the pipeline architecture, the Shadow Slave lore/story/characters after Volume 9.*

The pipeline already **uses** emotion and formatting, but **nothing measures whether either is working**:

- **Emotion**: each line gets an 8-dim vector + `emo_alpha` from `INDEXTTS2_EMOTION_VECTORS` (13 tags) in
  `src/tts_engine.py`, passed into `IndexTTS2.infer()`. Order: `[happy, angry, sad, afraid, disgust,
  melancholic, surprised, calm]`; `neutral` → pure timbre. There is **no test that measures the acoustic
  effect** — `tests/test_tts_engine.py` only checks resolution/wiring with `_synthesize` monkeypatched.
- **Accuracy**: completely unmeasured objectively. No ASR/Whisper, no WER, no speaker-similarity, no prosody
  analysis anywhere in the repo. `src/qa_audit.py` only does duration/completion heuristics via ffprobe.
- **Formatting**: deterministic segmentation (`src/segmenter.py`, byte-exact Pass 1) + LLM labeling
  (`src/llm_director.py`, grammar-locked to roster + emotion enum, Pass 2). Tested only with a **mocked LLM**
  (`tests/test_llm_director.py`) — real labeling accuracy vs ground truth is unmeasured.
- **Roster**: `DEFAULT_SPEAKERS` + `SPEAKER_ALIASES` (in `src/llm_director.py` / mirrored in
  `src/tts_engine.py` resolution) are curated for the Sunny/Rain arcs. Post-Vol-9 coverage is unverified.

The constraint throughout: **read-only on the pipeline's behavior** during the measurement phase (mirror the
existing QA-gate philosophy in `qa_audit.py` — never mutate state). Improvements come in Phase 2, gated on
numbers. 12 GB VRAM sequential constraint and Iraq power-cut limits (short ranges, per-line resume) still hold.

---

## Phase 0 — Test corpus & ground truth (prerequisite)

1. **Pick the corpus.** 2–3 chapters that exercise variety:
   - one already-complete verified chapter (regression anchor — e.g. ch 264 / vol9),
   - one **post-Volume-9** chapter (stresses roster gaps + new characters),
   - one dialogue-dense chapter (many speaker switches + emotion range).
2. **Gold labels (formatting/diarization ground truth).** Reuse existing tooling — do NOT hand-roll:
   - Export with `scripts/diarize_io.py` / `src/diarization_io.py` (`format-cloud` payload).
   - Send to a stronger cloud LLM for reference speaker+emotion labels.
   - Spot-correct the cloud output by hand (you), import back as the gold set.
   - This is the same round-trip already shipped (`16cccb9`, `db4dc97`, `e6eea73`).
3. **Gold transcript (accuracy ground truth).** The segmenter output text IS the intended spoken text
   (byte-exact). Use it directly as the ASR reference — no extra labeling needed.

Deliverable: `tests/data/gold/<chapter>.json` (speaker+emotion per line) + the segmenter text as ASR ref.

---

## Phase 1 — Build the measurement harness (objective)

New CPU-only scripts under `scripts/` (no GPU; operate on already-generated WAVs in `data/audio/ch_XXXX/`).
New deps: `openai-whisper` (or `faster-whisper`), `librosa`, `resemblyzer` (or speechbrain ECAPA). All
CPU-capable. Pin in a new `requirements-eval.txt` so the core runtime stays lean.

### 1a. TTS accuracy — `scripts/eval_accuracy.py`
- Run Whisper ASR on every line WAV → transcript.
- Compute **WER/CER** vs the segmenter's intended text (the gold transcript from Phase 0).
- Flag lines over a WER threshold (dropped words, hallucinated audio, truncation).
- Output: per-line CSV + chapter-level WER summary.

### 1b. Emotion effect — `scripts/eval_emotion.py`
- This is the core of your question: *does the emotion vector actually change the voice?*
- For a fixed set of probe sentences + one reference voice, synthesize the SAME line under each of the 13
  `INDEXTTS2_EMOTION_VECTORS` tags (plus `neutral` baseline) at a few `emo_alpha` levels.
- Extract prosody features with librosa: **F0 mean/std (pitch), energy/RMS, speaking rate, duration**.
- Produce a **delta matrix**: feature shift of each emotion vs `neutral`. This objectively shows which tags
  move the voice (e.g. `angry` → higher energy/F0) and which are **inert or indistinguishable** (the failure
  mode worth finding — a tag that sounds identical to neutral is wasted).
- Output: heatmap CSV (emotion × feature) + flag for "no measurable effect" tags.
- NOTE: this is the one part that NEEDS the GPU (it synthesizes). Keep the probe set small (~10 lines × 14
  conditions) and run it inside one `with TTSEngine(...)` block to respect the VRAM lifecycle.

### 1c. Voice consistency — `scripts/eval_speaker.py`
- Speaker-embedding (resemblyzer) cosine similarity between each character's reference clip and their
  generated lines.
- Flags voice drift / identity bleed, and quantifies emotion-vs-identity decoupling (does a strong emotion
  alpha degrade speaker similarity?).
- Output: per-speaker mean similarity + worst offenders.

### 1d. Formatting/diarization accuracy — `scripts/eval_formatting.py`
- Compare live diarizer output (`llm_director` Pass 2 labels in `state_manager`) vs the Phase-0 gold set.
- Metrics: **speaker label accuracy**, **emotion label accuracy**, confusion matrix, segmentation
  boundary check (Pass 1 is byte-exact so this should be 100% — verify it).
- Reuses the `unmapped speakers` pre-flight logic already in `src/qa_audit.py`.
- Output: accuracy %, confusion matrix, list of mislabeled lines.

### 1e. Human A/B protocol — `docs/listening-protocol.md`
- Structured scoring sheet (1–5: naturalness, emotion-appropriateness, character fit, artifacts).
- A/B pairs: neutral-vector vs emotion-vector for the same line; current roster voice vs candidate.
- This is where YOUR ears settle what metrics can't (naturalness). Ties back to the existing
  beam-quality listening check habit (`ch_0267.mp3`).

Deliverable: one runner `scripts/eval_all.py` that produces a `docs/eval-report-<date>.md` with all numbers.

---

## Phase 2 — Recommend & implement (gated on Phase 1 numbers)

Only do the items the measurements justify. Candidate levers, in likely-impact order:

1. **Retune `INDEXTTS2_EMOTION_VECTORS`** — for any tag flagged "inert" in 1b, adjust the vector/alpha so it
   produces a measurable, appropriate prosody delta without hurting speaker similarity (1c). Re-run 1b/1c to
   confirm. This is the highest-leverage fix for "emotions affecting the voice".
2. **Best-formatting improvements** — based on 1d confusion matrix: tighten the `llm_director` Pass-2 prompt
   / grammar where specific speaker or emotion confusions recur; consider few-shot anchors for ambiguous
   cases (inner-monologue single-quotes convention already known for this EPUB).
3. **Post-Volume-9 roster audit** — derive the actual speaker list from the EPUB text (frequency of named
   dialogue speakers in chapters after vol 9, via `epub_parser`), diff against `DEFAULT_SPEAKERS` /
   `SPEAKER_ALIASES`, and flag missing characters or aliases. Grounded in the source text, not lore memory.
   Add voices for high-frequency uncovered speakers (`sm.set_voice`). Keeps lore/characters intact.
4. **Accuracy fixes** — for high-WER lines (1a): check for segmenter edge cases (numbers, unusual
   punctuation) feeding bad text to TTS; fix in `segmenter.py` if systemic.

Each change ships as its own small commit with a before/after metric delta in the message.

---

## Verification

- **Unit**: add `tests/test_eval_*.py` for each scorer with tiny fixtures (mock Whisper/librosa outputs);
  keep them GPU-free and fast, matching existing test patterns (monkeypatch heavy deps).
- **Smoke**: `python scripts/eval_all.py --chapter <id>` on one corpus chapter end-to-end → produces report.
- **Regression**: re-run `scripts/qa_audit.py` (exit 0) after any Phase-2 change to confirm no integrity drop.
- **Human**: fill `docs/listening-protocol.md` for the A/B pairs before locking any emotion-vector change.
- **Gate**: a Phase-2 change is accepted only if its target metric improves AND speaker similarity (1c) and
  WER (1a) do not regress.

## Files this plan touches

| Action | Path |
|--------|------|
| NEW | `scripts/eval_accuracy.py`, `eval_emotion.py`, `eval_speaker.py`, `eval_formatting.py`, `eval_all.py` |
| NEW | `requirements-eval.txt`, `docs/listening-protocol.md`, `docs/eval-report-<date>.md`, `tests/data/gold/` |
| NEW | `tests/test_eval_*.py` |
| EDIT (Phase 2, gated) | `src/tts_engine.py` (`INDEXTTS2_EMOTION_VECTORS`), `src/llm_director.py` (roster + Pass-2 prompt), `src/segmenter.py` (edge cases) |
| REUSE | `src/diarization_io.py`, `scripts/diarize_io.py` (gold set), `src/qa_audit.py` (pre-flight logic), `src/epub_parser.py` (roster audit) |
