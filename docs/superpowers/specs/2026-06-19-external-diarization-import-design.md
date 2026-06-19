# External Diarization Import — Design

**Date:** 2026-06-19
**Status:** Approved (design)
**Origin:** Brainstorming session 2026-06-19 (branch `feat/correctness-audit`).
The local Qwen3-14B diarization stage is the slow, power-hungry half of the
pipeline — it loads ~9 GB and runs per chapter, which is exactly the part that
hurts on a 12 GB power-cut-prone machine in Iraq. This feature lets the user
diarize **anywhere** (a cloud LLM, a stronger local model, or by hand) and import
the result, skipping the local LLM entirely for those chapters.

## Goal

Let the user supply **pre-formatted (diarized) chapters from an external source**
instead of running `LLMDirector`. Export the deterministic segments of a chapter,
format them anywhere, and import speaker+emotion labels back — producing exactly
the same `status='diarized'` DB state the local LLM would have produced. The
orchestrator already skips the LLM stage for `diarized` chapters, so this needs
**zero orchestrator changes**.

## Core design decision: labels-only round-trip

The import path **never trusts external text.** Text is the one thing that must
stay byte-for-byte faithful to the EPUB (see [[project_verbatim_design]]). The
external source contributes *only* speaker and emotion, applied **by segment
index**.

Mechanism:

1. **Export** re-runs the deterministic `segment_chunk()` over the chapter's
   stored DB chunks (`get_chunks_for_chapter`) to produce a canonical, indexed
   segment list. Text in the export is verbatim-from-EPUB, for the formatter to
   *read* — not to echo back.
2. **Format** (anywhere): produce a `labels.json` mapping each segment index to a
   `{speaker, emotion}`.
3. **Import** re-runs the *same* `segment_chunk()` over the *same* stored chunks,
   then applies the external labels by index, runs them through the identical
   enforcement safety net the LLM path uses, and saves via
   `sm.save_diarized_lines()` → `status='diarized'`.

Because both ends re-segment deterministically from the same DB chunks, indices
are stable and the text never round-trips through an untrusted channel. A
mismatch in segment count between export and import means the export is stale
(EPUB re-parsed) → import refuses with a clear "re-export" error.

## Non-goals (v1)

- No change to the orchestrator, the chapter status lifecycle, or the TTS/assemble
  stages. Import lands a chapter at `diarized`; everything downstream is unchanged.
- No partial-chapter import. Labels cover a whole chapter's segments or the import
  is rejected (stale-export guard).
- No automatic re-export when the EPUB changes — the count-mismatch guard surfaces
  it; re-export is the user's explicit action.
- No new diarization *quality* logic. Enforcement is exactly the existing safety
  net, no more, no less.

## Architecture

Four pieces, mirroring the correctness-audit split (pure core + CLI + API + UI):

1. **`src/diarization_io.py`** — pure, GPU-free, **no `llama_cpp` import** so it's
   unit-testable without the model. Holds export / import / validate. Target
   < 350 lines.
2. **`scripts/diarize_io.py`** — CLI wrapper: `export`, `import`, `format-cloud`.
   Per-chapter resumable, reusable like `scripts/measure_swap_tax.py`.
3. **API** in `src/api.py` — `GET /api/chapters/{id}/segments` (export) and
   `POST /api/chapters/{id}/labels` (import). Read/write but scoped to one chapter.
4. **UI** — new section in `InspectorPanel.tsx`: download the export, upload one or
   many `labels.json` files (loops the per-chapter API).

### The shared enforcement refactor (the one source change to existing code)

Today `LLMDirector._merge_labels` (src/llm_director.py:464) does the structural
safety net — prose→Narrator (except genuine Sunny inner monologue via
`_is_narrator_misattribution`), thought→POV-character/Sunny, system→roster-or-Spell,
dialogue≠Narrator→Unknown, bad emotion→neutral. The importer must apply the
**identical** net, so we extract the body into a pure module-level function:

```python
# src/llm_director.py
def enforce_labels(
    segments: list[dict],                       # [{index, kind, text}, ...]
    labels:   dict[int, tuple[str, str]],       # index -> (speaker, emotion)
    allowed:  set[str],                         # roster incl. Narrator/Unknown/Spell
    line_offset: int = 0,
) -> list[dict]:                                # [{line_index, speaker, text, emotion}]
    ...
```

`LLMDirector._merge_labels` becomes a thin wrapper:
`return enforce_labels(segments, labels, self._allowed, line_offset)`. This keeps
the LLM path byte-identical (covered by existing `test_llm_director.py`) and gives
the importer the exact same enforcement. `enforce_labels` stays in `llm_director.py`
(it owns `_is_narrator_misattribution`, `EMOTION_VOCAB`, `SYSTEM_SPEAKER`,
`KIND_*`); `diarization_io.py` imports it. Importing `enforce_labels` does **not**
pull in `llama_cpp` (that's lazy-loaded inside `LLMDirector.__enter__`), so the
importer stays GPU-free.

## File formats

Per-chapter, keyed by `chapter_id`, filename `ch_XXXX` where `XXXX = chapter_id`
zero-padded to 4 (matches the `data/audio/ch_XXXX` / `data/output/ch_XXXX`
convention).

### Export — `ch_XXXX.segments.json`

```json
{
  "chapter_id": 258,
  "chapter_index": 258,
  "title": "...",
  "speakers": ["Narrator", "Sunny", "Nephis", "...", "Unknown", "The Nightmare Spell"],
  "segments": [
    {"i": 0, "kind": "prose",    "text": "The fortress loomed..."},
    {"i": 1, "kind": "dialogue", "text": "\"We move at dawn.\""}
  ]
}
```

- `kind` is the human-readable `KIND_*` value (`prose|dialogue|thought|system`).
- `speakers` is the chapter roster the formatter must choose from (the same set
  fed to the LLM system prompt: `Narrator` + project speakers + `Unknown` +
  `The Nightmare Spell`).
- `text` is verbatim-from-EPUB, present for the formatter to read for context only.

### Export — `system_prompt.txt` (one per batch)

The exact instruction block a cloud LLM / human needs: the roster, the
`EMOTION_VOCAB`, the per-kind labelling rules, and the required output schema. This
is generated from the same constants the local system prompt uses, so an external
formatter produces labels the enforcement net will accept without surprises.

### Import — `ch_XXXX.labels.json`

The **exact schema the local LLM emits** — `{labels: [{i, speaker, emotion}, ...]}`:

```json
{
  "chapter_id": 258,
  "labels": [
    {"i": 0, "speaker": "Narrator", "emotion": "neutral"},
    {"i": 1, "speaker": "Nephis",   "emotion": "resolute"}
  ]
}
```

## Import validation & error handling

- **Resolve** chapter by `chapter_id`; 404 / `ValueError` if absent.
- **Count match:** `len(labels) == len(re-segmented segments)`; otherwise reject
  with `"stale export, re-export chapter {id}"`. This is the verbatim/index-drift
  guard.
- **Index coverage:** every index `0..N-1` present exactly once; duplicates or
  gaps → reject.
- **Repair, don't reject, for label content:** out-of-roster speaker or
  out-of-vocab emotion is fixed by `enforce_labels` (→ Unknown / neutral / per-kind
  default), exactly as the LLM path self-heals.
- **Clobber guard:** refuse to overwrite a chapter already past `diarized`
  (`tts_done` / `assembled` / `complete`) unless `--force` (CLI) / `force=true`
  (API). A `diarized` or `pending` chapter imports freely.

## CLI behavior (`scripts/diarize_io.py`)

- `export --project NAME [--range A B] [--out DIR]` — writes
  `ch_XXXX.segments.json` per chapter + one `system_prompt.txt`. Resumable
  (skips chapters already exported unless `--force`).
- `import --project NAME --in DIR [--force]` — loads every `ch_XXXX.labels.json`
  in `DIR`, validates + imports each, prints a per-chapter result line; exit `0`
  if all imported, `1` if any rejected.
- `format-cloud --in DIR [--model ...]` — optional convenience: a **guarded**
  `import anthropic` (clear error if the package/key is absent), reads
  `segments.json` + `system_prompt.txt`, calls the API for labels JSON, writes
  `ch_XXXX.labels.json`, **skips chapters already formatted** (resumable). Kept
  separate from `import` so the core import path has zero network/SDK dependency.

## API behavior

- `GET /api/chapters/{chapter_id}/segments` → the `ch_XXXX.segments.json` payload
  for one chapter (re-segmented live; read-only). Reuses `get_sm`.
- `POST /api/chapters/{chapter_id}/labels` body = the `labels.json` payload,
  optional `?force=true`. Validates + imports via `diarization_io`, returns
  `{chapter_id, lines, status}` on success or `400/404/409` with the reason.
  `409 Conflict` for the clobber guard.

## UI (`InspectorPanel.tsx`)

A new "External diarization" section, visible for `pending` / `diarized` chapters:

- **Export** button → downloads the chapter's `segments.json` (and a batch
  `system_prompt.txt`).
- **Upload labels** → multi-file picker; loops the selected `ch_XXXX.labels.json`
  files, POSTing each to `/api/chapters/{id}/labels`, showing per-file
  success/failure. On success the chapter card flips to `diarized` (existing
  status-card styling, [[project_ui_redesign]]).

## Testing (`tests/test_diarization_io.py`)

GPU-free, monkeypatch style, temp-SQLite `StateManager` — same pattern as the
existing `tests/test_*.py`:

1. **Round-trip:** seed fixture chunks → export → synthesize labels for every
   index → import → assert the saved lines match expected speaker/emotion/text and
   `status == 'diarized'`.
2. **Enforcement parity:** run the *same* segments+labels through
   `LLMDirector._merge_labels` and through the importer; assert **identical** line
   dicts. This is the regression lock that the refactor didn't change LLM behavior.
3. **Stale-export guard:** labels count ≠ segment count → import rejects.
4. **Index coverage:** duplicate / missing index → rejects.
5. **Repair:** out-of-roster speaker + bad emotion → repaired, not rejected.
6. **Clobber guard:** importing over a `complete` chapter without force → rejected;
   with force → accepted.
7. **API:** `TestClient` with `app.dependency_overrides` for `get_sm` — GET
   segments returns the payload; POST labels imports; POST over a finished chapter
   returns 409.

## File-size discipline

`src/diarization_io.py` ≈ 300 lines (well under 500). If `format-cloud` grows,
split the Anthropic client into its own helper. The `llm_director.py` change is a
pure extraction — net line delta near zero.

## Key codebase anchors (verified 2026-06-19)

| Symbol | Location | Role |
|--------|----------|------|
| `_merge_labels` | `src/llm_director.py:464` | body extracted → `enforce_labels` |
| `_is_narrator_misattribution` | `src/llm_director.py:294` | used inside enforcement |
| `EMOTION_VOCAB` / `SYSTEM_SPEAKER` / `_KIND_TAGS` | `src/llm_director.py:71,77,79` | roster/vocab/schema source |
| `segment_chunk` | `src/llm_director.py` (imported in `_process_chunk:532`) | deterministic re-segmentation |
| `get_chunks_for_chapter` | `src/state_manager.py:380` | source chunks for re-segmentation |
| `get_chapter_by_id` / `get_project` | `src/state_manager.py:299,242` | chapter/roster resolution |
| `save_diarized_lines` | `src/state_manager.py:393` | sets `status='diarized'` |

Line dict contract: `{line_index, speaker, text, emotion}`. Roster set =
`{"Narrator", "Unknown", SYSTEM_SPEAKER, *project_speakers}`.
