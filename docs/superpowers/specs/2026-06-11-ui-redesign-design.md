# UI Redesign — "Nightmare Spell Command Deck"

**Date:** 2026-06-11
**Status:** Approved by user (all five design sections walked through and confirmed)
**Mockup of record:** `.superpowers/brainstorm/1947-1781134750/content/command-deck-v5-dramatic.html` (gitignored; v5-dramatic with ✦ star marks)

## 1. Goal and scope

Replace the current UI's visual layer and layout ("Abyssal Y2K" card grid + sidebar) with a new look: a gothic grayscale **Command Deck**. Full feature parity with the current UI — nothing is dropped, everything is re-housed. Battle-tested component logic is reused and reskinned; only the shell is rewritten.

Out of scope: backend behavior changes (except one additive SSE field change, §5.2), pipeline logic, database schema.

## 2. Visual system — "Nightmare Spell"

- **Palette:** pure grayscale — `#000000, #0a0a0a, #111111, #232323, #343434, #464646, #575757, #696969, #7a7a7a`; text `#bdbdbd–#e8e8e8`; **white `#ffffff` is reserved for active/live elements only**.
- **Crimson (variant A2):** `#8c2731` / text `#b85560` / bg `#150b0c` — used **exclusively** for errors and destructive confirms. Nothing else is ever red. Warnings (e.g. `vram_warning`) use bright white, not crimson.
- **Status/brand mark:** the four-pointed star `✦` (matches Shadow Slave branding). Used for: queue row status marks (grey = pending, lighter = complete, crimson = failed, white breathing = running), the header live indicator, the giant ghost watermark, the stage corner ornament, the player seek thumb. The `◆` diamond from earlier mockups is retired.
- **Typography:** Cinzel (display: wordmark, chapter titles, buttons, tabs), IBM Plex Mono (numbers/data), Inter (body).
- **Dramatic layer (from v5):** page vignette + radial fog, giant ghost `✦` watermark bottom-right, flickering wordmark, glow-pulse on the running row, 3-bar equalizer next to "Synthesizing", shimmer sweep on progress bars, glowing live stage. Proportions are v5's — do **not** impose uniform fixed heights (the v6 rhythm pass was explicitly rejected).
- Radii stay small (4–6px); hover states use white glow (`rgba(255,255,255,…)` shadows), never color.

## 3. Layout — "Command Deck"

Single-screen app, no page scroll; three zones:

```
┌──────────────────────────────────────────────────────────────┐
│ HEADER  brand · RUN/PAUSE/STOP · stats (live ✦ status,       │
│         chapters done/total, ETA, VRAM)                      │
├───────────────────────────────┬──────────────────────────────┤
│ CHAPTER QUEUE (flex 1.8)      │ INSPECTOR (330–430px)        │
│ filter tabs: All/Pending/     │ tabs: Inspector|Voices|      │
│   Complete/Failed + search    │       Forge|Log              │
│ dense rows: № ✦ title sub     │ ┌ live stage: chapter title, │
│   hover-only ops ▶ ↻ ✕        │ │ current line text, speaker │
│ running row: enlarged, glow,  │ │ + emotion, progress + ETA  │
│   equalizer, progress bar     │ └ detail: lines/words/voices │
│                               │   speaker histogram, actions │
├───────────────────────────────┴──────────────────────────────┤
│ PLAYER  play/pause · now playing + up next · seek · time ·   │
│         speed                                                │
└──────────────────────────────────────────────────────────────┘
```

- **Chapter queue** replaces the card grid: one dense row per chapter (№, ✦ mark, title, status sub-line, hover-only row actions). The running chapter's row is one step taller with equalizer, progress bar, and glow-pulse.
- **Inspector panel** (right column) replaces the sidebar tabs. Tab set: **Inspector** (live stage + selected-chapter detail), **Voices** (VoiceMapper), **Forge** (project setup / generation options), **Log** (LiveLog). The top "live stage" area shows the in-flight line during synthesis; when idle, it shows the selected chapter.
- **Player bar** docked at the bottom (reuses PlayerBar logic: queue of completed chapters, auto-advance, prev/next/seek/speed/volume, localStorage prefs, keyboard shortcuts).
- Toasts remain top-right, bracketed Nightmare-Spell style.

## 4. Implementation approach

**Approach 1 (chosen): rewrite the shell, reuse the leaves.**

- **New:** design tokens (tailwind config + globals.css rewritten to the grayscale system), `CommandStrip` (header), `ChapterQueue` (replaces ChapterGrid), `InspectorPanel` (tabs + live stage + detail), plus a `usePipelineState` hook (§5.3).
- **Reused, reskinned only:** `PlayerBar`, `ConfirmButton`, `Toasts`, `useSSE`, `lib/api.ts`, `lib/types.ts`, `VoiceMapper`, `LiveLog`, `ProjectSetup` (the last three render inside Inspector tabs).
- **Removed:** `ChapterGrid`, `StatsBar`/ChapterStrip minimap (its jump-to-chapter role is covered by the queue's filter tabs + search; its at-a-glance progress role by the header stats), `EmptyState` (replaced by an idle state of the Command Deck), the old sidebar layout in `page.tsx`.
- Every file stays under 500 lines; `page.tsx` becomes a thin layout shell.

## 5. Data flow

### 5.1 What stays
- `useSSE`: direct `EventSource` to FastAPI `:8000/api/events`, 3 s auto-reconnect.
- Hybrid sync: SSE for live deltas; snapshot refetches (`getChapters`, progress) on `chapter_done`, `chapter_error`, `pipeline_done`, `pipeline_stopped`, and after reconnect, so the UI self-heals.

### 5.2 Backend rider (the only backend change)
`TTSEngine.process_chapter`'s progress callback (`src/tts_engine.py:418`) grows from `(lines_done, lines_total)` to also pass the current line's `text`, `speaker`, `emotion`. The orchestrator's `_tts_progress` closure (`src/orchestrator.py:319`) adds them to the `tts_progress` SSE event, truncating text to ~200 chars server-side. `SSEEvent` in `ui/lib/types.ts` gains the three optional fields. This feeds the Inspector live stage.

### 5.3 State ownership
All pipeline state moves from `page.tsx`'s ~15 `useState`s into one `usePipelineState()` hook — a reducer over SSE events exposing `{ pipeStatus, chapters, progress, activeChapter, activeStage, liveLine, log, toasts }`. CommandStrip, ChapterQueue, InspectorPanel, and PlayerBar all read from this single source. The reducer is a pure function and unit-testable without rendering.

### 5.4 Diarize stage
No per-line events exist for diarization (the LLM processes chunks). The live stage shows the stage label + elapsed time with an indeterminate shimmer — no fake progress bar, and no new `diarize_progress` event (deliberately deferred).

## 6. Error handling

- **Failed chapter rows:** crimson treatment (the only crimson in the app): blood-tinted row, crimson ✦, sub-line shows failed stage + short error excerpt (parsed from `error_message`'s `[failed_stage:X]` prefix — existing format, unchanged).
- **Inspector for a failed chapter:** full error text; **Retry** (resumes from failed stage — existing backend logic) and **Reset** (back to pending), both behind `ConfirmButton` two-step confirms restyled crimson.
- **Toasts:** `chapter_error` / `pipeline_error` crimson; `vram_warning` bright white with breathing animation (gold is gone; crimson is reserved for true errors); `pipeline_done` bright congratulatory toast.
- **Connection loss:** header live ✦ dims and status reads "LINK SEVERED" while disconnected; auto-reconnect + snapshot re-sync restores it.
- **Control-action HTTP failures** (Run/Pause/Stop/Retry/Reset): crimson toast instead of silent catch.
- **Backend:** error model and resume logic untouched.

## 7. Testing

- **`usePipelineState` unit tests (vitest):** feed event sequences (start → tts_progress → chapter_done; error paths; reconnect re-sync) and assert derived state.
- **Component tests:** ChapterQueue (filters, search, status rendering, failed-row treatment), InspectorPanel (tab switching, live stage fields), CommandStrip (control enable/disable per pipeline status).
- **Reused leaves keep their existing tests** (PlayerBar, ConfirmButton, Toasts) — reskins must not change behavior.
- **Gates:** `vitest run`, `tsc --noEmit`, `next build` all clean.
- **Backend (python, monkeypatched):** new test that `process_chapter` passes line text/speaker/emotion to the callback; updated test that the `tts_progress` event carries the new fields and truncates long text; all 60 existing python tests stay green.
- **Manual gate:** one live pipeline run on a real chapter with the new UI before completion.

## 8. Mockup iteration history (for the record)

v1 dense table (rejected: not visually friendly) → v2 rounded cards (rejected: looks AI-made) → v3 TOC dot-leaders (rejected) → v4 clean keeper → **v5-dramatic = v4 + theatrics (approved direction)** → v6 fixed-height rhythm pass (explicitly rejected and deleted; do not redo) → ✦ star marks replace ◆ diamonds (approved 2026-06-11).
