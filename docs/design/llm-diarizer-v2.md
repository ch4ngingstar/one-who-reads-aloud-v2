# LLM Diarizer v2 — Label-Only Two-Pass Design

**Date:** 2026-06-12
**Status:** Approved
**Goal:** Maximise diarization quality on all four axes — attribution accuracy, model quality, output robustness, speed — by restructuring the LLM stage from "echo the whole text as JSON" to "deterministic segmentation + label-only LLM pass".

## Problem

The current `llm_director.py` makes the LLM reproduce the entire chapter text inside its JSON output. This is the root cause of:

- **Word loss** — the LLM silently drops sentences; a coverage guard + retries + Narrator-fallback exist only to fight this.
- **JSON leak artifacts** — fragments like `','emotion":"neutral` bleeding into spoken text.
- **Slow generation** — ~6,000 output tokens per chunk.
- **Invalid speakers/emotions** — free-text fields require a post-hoc misattribution heuristic.

Verified facts that shape the design:

- Italics do **not** survive EPUB parsing (`p.get_text()` strips tags; zero `*…*` spans in the DB). Prompt rules keyed to italic markers are dead code.
- Dialogue uses straight `"` (dominant) and curly `“”` quotes. Single quotes are overwhelmingly apostrophes — not used for splitting.
- Square brackets carry both standalone Nightmare Spell notifications (`[You have slain a Great Demon.]`) and inline game refs (`[Silver Bell]`, `[1591/6000]`).
- Model path arrives via the API request (`llm_model_path`); a model swap is config, not code.

## Architecture

```
chunk text
   │
   ▼
segmenter.py  (pass 1 — deterministic Python)
   │   segments: [{index, kind: dialogue|system|prose, text}]
   ▼
llm_director.py  (pass 2 — LLM labels only)
   │   {"labels":[{"i":0,"speaker":"…","emotion":"…"}]}   ← grammar-locked
   ▼
structural enforcement + merge → lines [{line_index, speaker, text, emotion}]
   ▼
sm.save_diarized_lines()   (contract unchanged — orchestrator/TTS/UI untouched)
```

### Pass 1 — `src/segmenter.py` (new, ~200 lines)

Per paragraph (`\n\n`-separated):

1. Scan for double-quote spans — straight `"…"` and curly `“…”` — and bracket spans `[…]`.
2. Emit ordered segments `{index, kind, text}`:
   - `dialogue` — quoted span, **quote marks stripped** (replaces prompt rule R3).
   - `system` — bracket span, but only when the trimmed paragraph consists entirely of bracket spans (one or more) and whitespace; each span becomes its own `system` segment. Inline refs (`[Silver Bell]` mid-sentence) stay inside prose.
   - `prose` — everything else, including attribution tails ("he said.").
3. **Unbalanced quotes** in a paragraph → that whole paragraph becomes one prose segment. Never guess at span boundaries.
4. Invariant: every character of input lands in exactly one segment, in order. Word loss is structurally impossible.

### Pass 2 — `src/llm_director.py` (rewritten, smaller)

- Prompt shows all numbered segments (prose included — context for attribution) tagged with kind.
- LLM returns **only** `{"labels":[{"i":int,"speaker":enum,"emotion":enum}]}`.
- System prompt shrinks to: roster, emotion vocab, character-emotion guide, attribution guidance, a handful of examples. R1/R3 echo rules and the coverage guard are deleted — the architecture makes those failures impossible.

### Structural speaker enforcement (replaces `_is_narrator_misattribution` as primary defence)

| Segment kind | Allowed speakers | Enforcement |
|---|---|---|
| `dialogue` | roster, `Unknown` | as labeled |
| `system` | `The Nightmare Spell` (default), `Narrator` | forced unless LLM picks the allowed alternative |
| `prose` | `Narrator`; `Sunny` only for inner monologue | `Sunny` accepted only if `_is_narrator_misattribution` agrees the text reads first-person; otherwise flipped to `Narrator` |

Prose keeps the LLM-chosen emotion (narrator gets `frightened`/`desperate` in horror scenes).

**Accepted trade-off:** unmarked inner monologue ("Signal B") will more often be read by the Narrator. Since italics never survive parsing, the prose→Sunny escape hatch (guarded) is the practical replacement.

### Grammar-locked decoding

- `LlamaGrammar.from_json_schema` (llama-cpp-python): `speaker` and `emotion` are JSON-schema enums, `i` an integer. Invalid JSON / speaker / emotion become impossible at the decoder.
- Post-validation: every segment index labeled exactly once. One retry on mismatch; then per-segment fallback — `dialogue→Unknown`, others→`Narrator`, emotion `neutral`.

### Model upgrade

- **Qwen3-14B Q4_K_M** (~9 GB, fits 12 GB VRAM at n_ctx 8192), non-thinking mode (`/no_think`).
- Sampling: temp 0.2, top_p 0.8 (Qwen non-thinking guidance, biased deterministic for classification).
- Backward compatible with Qwen2.5 GGUFs. Docstring and download instructions updated.

### Speed

- Output tokens ~6,000 → ~500 per chunk (~10×).
- `flash_attn=True`; `max_tokens` 2048; llama.cpp prefix cache reuses the static system prompt across chunks.
- Grammar removes nearly all parse retries.

## Addendum (implementation finding, same date)

During verification against the full DB (2,081 chunks), a fourth structural signal emerged: **this EPUB marks inner monologue with single quotes** — 595 wholly-wrapped paragraphs (`'That went better than expected.'`) plus 106 inline spans. A fourth segment kind **`thought`** was added:

- Detected at word boundaries only (contractions/possessives like `I'll`, `guards'` never split); outer quotes stripped.
- Prompt tag `[T]`; LLM labels the scene's POV character (Sunny in Sunny-POV, Rain in Rain-POV).
- Enforcement: any roster label trusted (no first-person guard — the quotes are the structural evidence; thoughts legitimately mention others in third person). Impossible labels repaired to `Sunny`; total-failure fallback is `Narrator` (safe in Rain-arc chapters).
- Bracket paragraphs with stray trailing punctuation (`[X.].`) now count as `system`.

This supersedes the assumption that no inner-monologue signal survives EPUB parsing. Verified: zero real word loss across all 2,081 chunks; kind distribution prose 28,313 / dialogue 4,074 / thought 723 / system 175.

## Unchanged contract

`sm.save_diarized_lines(chapter_id, lines)` with `[{line_index, speaker, text, emotion}]`. DB schema, orchestrator, TTS, UI: no changes.

## Testing

`tests/test_llm_director.py` rewritten:

- **Segmenter:** straight/curly quotes, unbalanced quotes, multi-paragraph, standalone vs inline brackets, attribution tails, full-coverage invariant (joined segments == source modulo stripped quote marks).
- **Labeling:** parse + index validation, mismatch retry, per-segment fallback.
- **Enforcement:** prose→Sunny guard accepts first-person, rejects third-person.
- **End-to-end:** `_call_llm` monkeypatched, no model load.
