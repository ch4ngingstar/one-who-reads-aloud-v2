# Nightmare Spell Command Deck — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the UI's visual layer and layout with the approved "Nightmare Spell Command Deck" design (grayscale gothic, ✦ star marks, dense chapter queue + Inspector panel), plus one backend rider: `tts_progress` SSE events carry the current line's text/speaker/emotion.

**Architecture:** Rewrite the shell (design tokens, CommandStrip header, ChapterQueue, InspectorPanel, `usePipelineState` reducer hook); reuse battle-tested leaves (PlayerBar, ConfirmButton, Toasts, useSSE, VoiceMapper, ProjectSetup, LiveLog) reskinned via the shared token/CSS rewrite. Backend changes are limited to the TTS progress callback signature and the orchestrator's `tts_progress` event payload.

**Tech Stack:** Next.js 15 + React 19 + Tailwind CSS, vitest + @testing-library/react, Python 3.11 (plain-assert test files with a `TESTS` list runner).

**Spec:** `docs/superpowers/specs/2026-06-11-ui-redesign-design.md`. Visual reference: `.superpowers/brainstorm/1947-1781134750/content/command-deck-v5-dramatic.html` (gitignored — open in a browser while styling).

**Known scope reduction vs. spec diagram:** the Inspector "speaker histogram" needs a per-chapter lines endpoint that doesn't exist; backend is frozen except the tts_progress rider, so the detail pane shows lines/chunks/size figures instead. Noted here so it isn't silently lost.

**Conventions used below:**
- All UI paths relative to `ui/`, backend paths relative to repo root (`C:\Users\alityan\OneDrive\Desktop\shaodw salve`).
- Python tests: each file has a `TESTS = [...]` list and a `__main__` runner. New test functions MUST be appended to that file's `TESTS` list or they will not run.
- Frontend gates: `cd ui; npm test` (vitest run), `cd ui; npm run typecheck`, `cd ui; npm run build`.
- Commit after every task. PowerShell is the shell — chain with `;`, not `&&`.

---

## File structure (end state)

| File | Action | Responsibility |
|---|---|---|
| `src/tts_engine.py` | modify | progress callback now `(lines_done, lines_total, line_dict)` |
| `src/orchestrator.py` | modify | `tts_progress` event gains `text`/`speaker`/`emotion`; `_truncate_live_text` helper |
| `tests/test_tts_engine.py` | modify | new callback test |
| `tests/test_orchestrator.py` | modify | FakeTTSEngine fires callback; new event-payload + truncation tests |
| `ui/lib/types.ts` | modify | `SSEEvent` gains `text`/`speaker`/`emotion` |
| `ui/hooks/useSSE.ts` | modify | optional `onConnection` callback |
| `ui/app/layout.tsx` | modify | fonts: Inter + Cinzel + IBM Plex Mono (drop VT323, Space Mono) |
| `ui/tailwind.config.ts` | modify | grayscale `spell`/`blood` palette; remapped `ink`/`dot`; new keyframes |
| `ui/app/globals.css` | rewrite | Nightmare Spell theme, same class names so reused leaves restyle for free |
| `ui/components/Toasts.tsx` | modify | tone `gold` → `warn` (bright white) |
| `ui/lib/format.ts` | create | `formatEta` (moved from StatsBar), `formatMB`, `parseChapterError` |
| `ui/hooks/usePipelineState.ts` | create | pure SSE reducer + hook (state of record for pipeline UI) |
| `ui/components/CommandStrip.tsx` | create | header: brand, RUN/PAUSE/STOP, live stats |
| `ui/components/ChapterQueue.tsx` | create | dense row queue, filters, search, running row |
| `ui/components/InspectorPanel.tsx` | create | tabs Inspector/Voices/Forge/Log, live stage, chapter detail |
| `ui/components/LiveLog.tsx` | modify | `embedded` prop so it can fill the Log tab |
| `ui/app/page.tsx` | rewrite | thin layout shell wiring everything |
| `ui/components/ChapterGrid.tsx` | delete | replaced by ChapterQueue |
| `ui/components/StatsBar.tsx` | delete | replaced by CommandStrip stats |
| `ui/components/EmptyState.tsx` | delete | replaced by queue idle state |
| `ui/tests/ChapterGrid.test.tsx` | delete | component gone |
| `ui/tests/usePipelineState.test.ts` | create | reducer unit tests |
| `ui/tests/format.test.ts` | create | helper tests |
| `ui/tests/CommandStrip.test.tsx` | create | header behavior |
| `ui/tests/ChapterQueue.test.tsx` | create | queue behavior |
| `ui/tests/InspectorPanel.test.tsx` | create | tabs + live stage |

---

### Task 1: Backend — TTS progress callback passes the line dict

**Files:**
- Modify: `src/tts_engine.py:415-426` (signature + docstring), `:456-457` and `:512-513` (call sites)
- Test: `tests/test_tts_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tts_engine.py` (after the existing integration tests, before the `TESTS` list). The helpers `_tmp_sm`, `_tmp_wav`, `_seed_diarized_chapter`, `_make_engine`, `_mock_synth` already exist in this file:

```python
def test_progress_callback_receives_line():
    # The callback must receive (lines_done, lines_total, line_dict) so the
    # orchestrator can put the live line on the tts_progress SSE event.
    sm = _tmp_sm()
    ch_id = _seed_diarized_chapter(sm, [
        {"line_index": 0, "speaker": "Sunny",    "text": "Hello there.", "emotion": "calm"},
        {"line_index": 1, "speaker": "Narrator", "text": "He waited.",   "emotion": "neutral"},
    ])
    sm.set_voice("_default", str(_tmp_wav()), "ref text")
    out = Path(tempfile.mkdtemp())
    engine = _make_engine(sm, out, mock_synth=_mock_synth)

    calls = []
    engine.process_chapter(
        ch_id,
        progress_callback=lambda done, total, line: calls.append((done, total, line)),
    )

    assert len(calls) == 2, f"expected 2 callback calls, got {len(calls)}"
    done, total, line = calls[0]
    assert (done, total) == (1, 2)
    assert line["speaker"] == "Sunny"
    assert line["text"]    == "Hello there."
    assert line["emotion"] == "calm"
    print("  PASS test_progress_callback_receives_line")
```

Then append `test_progress_callback_receives_line,` to the `TESTS` list near the bottom of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_tts_engine.py`
Expected: `FAIL test_progress_callback_receives_line: <lambda>() missing 1 required positional argument: 'line'` (every other test still passes).

- [ ] **Step 3: Update the callback contract**

In `src/tts_engine.py`, change the `process_chapter` signature and docstring:

```python
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
```

Change BOTH call sites (the skip path and the end-of-loop path) from
`progress_callback(processed, total)` to:

```python
                if progress_callback:
                    progress_callback(processed, total, line)
```

(The skip-path occurrence sits inside the `if ref_info is None:` block; the other is the last statement of the `for processed, line in enumerate(lines, start=1):` loop body. Same three-argument call in both.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python tests/test_tts_engine.py`
Expected: all tests pass, including `PASS test_progress_callback_receives_line`.

- [ ] **Step 5: Commit**

```powershell
git add src/tts_engine.py tests/test_tts_engine.py
git commit -m "feat(tts): progress callback passes the just-processed line dict"
```

---

### Task 2: Backend — `tts_progress` event carries text/speaker/emotion

**Files:**
- Modify: `src/orchestrator.py` (module constant + helper near the top; `_tts_progress` closure at `:319-323`)
- Test: `tests/test_orchestrator.py` (FakeTTSEngine at `:50-66`, new tests)

- [ ] **Step 1: Update FakeTTSEngine to the new contract and write the failing tests**

In `tests/test_orchestrator.py`, replace `FakeTTSEngine.process_chapter` with:

```python
    def process_chapter(self, chapter_id, progress_callback=None):
        lines = self.sm.get_pending_tts_lines(chapter_id)
        total = len(lines)
        for i, line in enumerate(lines, start=1):
            self.sm.mark_line_tts_done(line["id"], f"/fake/audio/line_{line['id']}.wav")
            if progress_callback:
                progress_callback(i, total, line)
        self.sm.mark_chapter_status(chapter_id, "tts_done")
        return total
```

Add two tests (before the `TESTS` list) and register both in `TESTS`:

```python
def test_tts_progress_event_carries_line_fields():
    # The SSE event behind the Inspector's live stage must include the line.
    orch = _make_orch()
    orch.run()
    evs = [e for e in orch.events if e["type"] == "tts_progress"]
    assert evs, "expected tts_progress events from the fake TTS engine"
    ev = evs[0]
    assert ev["lines_done"] == 1
    assert ev["speaker"] == "Narrator"
    assert ev["text"]    == "Test line."
    assert ev["emotion"] == "neutral"
    print("  PASS test_tts_progress_event_carries_line_fields")


def test_live_text_is_truncated():
    from orchestrator import _truncate_live_text, _LIVE_TEXT_MAX_CHARS
    long = "x" * 500
    out = _truncate_live_text(long)
    assert len(out) == _LIVE_TEXT_MAX_CHARS
    assert out.endswith("…")
    assert _truncate_live_text("short") == "short"
    assert _truncate_live_text(None) == ""
    print("  PASS test_live_text_is_truncated")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tests/test_orchestrator.py`
Expected: `test_tts_progress_event_carries_line_fields` fails with `KeyError: 'speaker'` (the orchestrator closure currently rejects 3 args → actually fails earlier with a TypeError inside run; either failure mode is fine), and `test_live_text_is_truncated` fails with ImportError.

- [ ] **Step 3: Implement in the orchestrator**

In `src/orchestrator.py`, add near the top of the module (after the existing module-level constants):

```python
# tts_progress events carry the live line for the UI's Inspector stage; cap
# the text so a single long paragraph can't bloat the SSE stream.
_LIVE_TEXT_MAX_CHARS = 200


def _truncate_live_text(text) -> str:
    text = str(text or "")
    if len(text) <= _LIVE_TEXT_MAX_CHARS:
        return text
    return text[: _LIVE_TEXT_MAX_CHARS - 1] + "…"
```

Replace the `_tts_progress` closure in `_stage_synthesize` (currently `src/orchestrator.py:319-323`) with:

```python
        def _tts_progress(lines_done: int, lines_total: int, line: dict) -> None:
            self._emit("tts_progress",
                       chapter_id=chapter_id,
                       lines_done=lines_done,
                       lines_total=lines_total,
                       text=_truncate_live_text(line.get("text")),
                       speaker=line.get("speaker"),
                       emotion=line.get("emotion"))
```

Note: `get_pending_tts_lines` rows may be `sqlite3.Row`; if `line.get` raises `AttributeError` when you run the real pipeline, convert first: `line = dict(line)` as the closure's first statement. The fakes use plain dicts so tests pass either way — add the `dict(line)` line defensively:

```python
        def _tts_progress(lines_done: int, lines_total: int, line: dict) -> None:
            line = dict(line)
            self._emit("tts_progress",
                       chapter_id=chapter_id,
                       lines_done=lines_done,
                       lines_total=lines_total,
                       text=_truncate_live_text(line.get("text")),
                       speaker=line.get("speaker"),
                       emotion=line.get("emotion"))
```

- [ ] **Step 4: Run all python suites**

Run: `python tests/test_orchestrator.py; python tests/test_tts_engine.py; python tests/test_api.py`
Expected: all pass (the api suite exercises the manager/SSE plumbing, which is payload-agnostic).

- [ ] **Step 5: Commit**

```powershell
git add src/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): tts_progress event carries live line text/speaker/emotion"
```

---

### Task 3: Frontend foundation — SSEEvent fields + useSSE connection signal

**Files:**
- Modify: `ui/lib/types.ts:62-83`, `ui/hooks/useSSE.ts`

- [ ] **Step 1: Extend SSEEvent**

In `ui/lib/types.ts`, inside `interface SSEEvent`, replace the `// tts_progress fields` block with:

```ts
  // tts_progress fields
  lines_done?: number
  lines_total?: number
  /** Live line being synthesised (truncated server-side to ~200 chars). */
  text?: string
  speaker?: string
  emotion?: string
```

- [ ] **Step 2: Add the connection callback to useSSE**

Replace `ui/hooks/useSSE.ts` with (only additions: `onConnection` param, `connRef`, `es.onopen`, the `onerror` notify):

```ts
'use client'
import { useEffect, useRef } from 'react'
import type { SSEEvent } from '@/lib/types'

type Handler = (event: SSEEvent) => void

const RECONNECT_DELAY_MS = 3000

export function useSSE(
  enabled: boolean,
  onEvent: Handler,
  onConnection?: (connected: boolean) => void,
) {
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent
  const connRef = useRef(onConnection)
  connRef.current = onConnection

  useEffect(() => {
    if (!enabled) return

    let es: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let disposed = false

    function connect() {
      if (disposed) return
      // Connect directly to the FastAPI backend — Next.js rewrites buffer SSE
      // which breaks streaming.
      const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      es = new EventSource(`${backendUrl}/api/events`)

      es.onopen = () => { connRef.current?.(true) }

      es.onmessage = (e) => {
        try {
          handlerRef.current(JSON.parse(e.data) as SSEEvent)
        } catch {
          // ignore malformed events
        }
      }

      es.onerror = () => {
        connRef.current?.(false)
        es?.close()
        es = null
        if (!disposed) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }

    connect()

    return () => {
      disposed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      es?.close()
      es = null
    }
  }, [enabled])
}
```

- [ ] **Step 3: Gates**

Run: `cd ui; npm run typecheck; npm test`
Expected: clean / all existing tests pass (no behavior change for existing callers — the third argument is optional).

- [ ] **Step 4: Commit**

```powershell
git add ui/lib/types.ts ui/hooks/useSSE.ts
git commit -m "feat(ui): SSEEvent live-line fields + useSSE connection callback"
```

---

### Task 4: Nightmare Spell theme — fonts, tokens, globals.css

The reused leaves (PlayerBar, ConfirmButton, Toasts, LiveLog, VoiceMapper, ProjectSetup) are reskinned **entirely by this task**: class names stay identical, values change. Old components (ChapterGrid/StatsBar/EmptyState) keep rendering until Task 10 — keep their token names alive (remapped) and prune in Task 10.

**Files:**
- Modify: `ui/app/layout.tsx`, `ui/tailwind.config.ts`
- Rewrite: `ui/app/globals.css`

- [ ] **Step 1: Fonts in layout.tsx**

Replace the font setup in `ui/app/layout.tsx` (keep metadata + body classes as-is):

```tsx
import type { Metadata } from 'next'
import { Inter, IBM_Plex_Mono, Cinzel } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

const plexMono = IBM_Plex_Mono({
  weight: ['400', '500'],
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

// Gothic display serif — wordmark, chapter titles, buttons, tabs.
const cinzel = Cinzel({
  weight: ['500', '700'],
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Shadow Slave — Audiobook Pipeline',
  description: 'Shadow Slave — multi-voice audiobook generation',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable} ${cinzel.variable}`}>
      <body className="bg-surface-base text-ink-primary antialiased min-h-screen font-sans dream-realm">
        {children}
      </body>
    </html>
  )
}
```

(VT323 and Space Mono are gone; `--font-tech` no longer exists — the config maps `font-tech`/`.tech` to the mono var so old components keep working until deleted.)

- [ ] **Step 2: tailwind.config.ts**

Replace `ui/tailwind.config.ts` with:

```ts
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './hooks/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        // VT323 retired — `.tech` data values now read in IBM Plex Mono.
        tech: ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        display: ['var(--font-display)', 'Cinzel', 'Georgia', 'serif'],
      },
      colors: {
        // ── Nightmare Spell grayscale ladder (spec §2) ────────────────────
        spell: {
          g0: '#000000', g05: '#0a0a0a', g1: '#111111', g2: '#232323',
          g3: '#343434', g4: '#464646', g5: '#575757', g6: '#696969', g7: '#7a7a7a',
        },
        // Crimson — errors and destructive confirms ONLY (variant A2).
        blood: { DEFAULT: '#8c2731', text: '#b85560', bg: '#150b0c' },
        // Legacy token names kept so reused/old components restyle for free.
        surface: { base: '#000000', raised: '#0a0a0a', card: '#111111', overlay: '#161616' },
        edge: {
          DEFAULT: '#232323',
          subtle:  'rgba(35,35,35,0.6)',
          bright:  '#343434',
          silver:  'rgba(255,255,255,0.12)',
          gold:    'rgba(255,255,255,0.12)',  // alias — gold is retired
          cyan:    'rgba(255,255,255,0.10)',  // alias — kept for compat
        },
        ink: {
          primary:   '#e8e8e8',
          secondary: '#c4c4c4',
          muted:     '#696969',
          ghost:     '#464646',
          hot:       '#ffffff',
        },
        soul: {  // pruned in Task 10 with ChapterGrid; remapped until then
          chrome: '#c4c4c4', gold: '#e8e8e8', crimson: '#8c2731',
          ash: '#696969', dim: '#464646', deep: '#000000',
        },
        accent: '#111111',
        dot: {
          pending:  '#343434',
          diarized: '#575757',
          tts:      '#696969',
          complete: '#c4c4c4',
          error:    '#b85560',
          running:  '#ffffff',
        },
      },
      borderWidth: { DEFAULT: '1px' },
      keyframes: {
        breathe: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.35' },
        },
        glowpulse: {
          '0%, 100%': { boxShadow: '0 0 26px rgba(255,255,255,0.07), inset 0 0 18px rgba(255,255,255,0.02)' },
          '50%':      { boxShadow: '0 0 48px rgba(255,255,255,0.14), inset 0 0 26px rgba(255,255,255,0.05)' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.06' },
          '50%':      { opacity: '0.35' },
        },
        flicker: {
          '0%, 91%, 94%, 97%, 100%': { opacity: '1' },
          '92%, 95%':                { opacity: '0.75' },
          '96%':                     { opacity: '0.85' },
        },
        'thread-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%':      { opacity: '0.7' },
        },
        'toast-in': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        equalize: {
          '0%, 100%': { transform: 'scaleY(0.3)' },
          '50%':      { transform: 'scaleY(1)' },
        },
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        breathe:        'breathe 2.4s ease-in-out infinite',
        glowpulse:      'glowpulse 3.2s ease-in-out infinite',
        'fade-in':      'fade-in 0.2s ease-out',
        'slide-up':     'slide-up 0.25s ease-out',
        twinkle:        'twinkle 3s ease-in-out infinite',
        flicker:        'flicker 7s ease-in-out infinite',
        'thread-pulse': 'thread-pulse 4s ease-in-out infinite',
        'toast-in':     'toast-in 0.22s ease-out',
        equalize:       'equalize 0.9s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
```

(Removed: `gold-glow`, `cyber-aura`, `wave`, `drift`, `flash-highlight` keyframes — only old components referenced them; Tailwind simply won't generate the classes, which is harmless until those components are deleted in Task 10.)

- [ ] **Step 3: globals.css rewrite**

Replace `ui/app/globals.css` with:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

/* ─────────────────────────────────────────────────────────────────────────────
   NIGHTMARE SPELL — grayscale gothic. White is for active/live elements only;
   crimson (#8c2731 family) is reserved for errors + destructive confirms.
───────────────────────────────────────────────────────────────────────────── */
@layer base {
  * { box-sizing: border-box; border-color: #232323; }

  html {
    color-scheme: dark;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  body {
    background-color: #000000;
    background-image: radial-gradient(ellipse 75% 55% at 50% -12%, #131313 0%, #000 72%);
    color: #c4c4c4;
    font-family: var(--font-sans), system-ui, sans-serif;
    font-size: 13px;
    line-height: 1.5;
  }

  ::-webkit-scrollbar        { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track  { background: transparent; }
  ::-webkit-scrollbar-thumb  { background: #232323; }
  ::-webkit-scrollbar-thumb:hover { background: #464646; }

  ::selection { background: rgba(255,255,255,0.14); color: #ffffff; }

  :focus-visible {
    outline: 1px solid rgba(255,255,255,0.45);
    outline-offset: 2px;
  }

  input:not([type='range']), textarea, select {
    background: #111111;
    color: #c4c4c4;
    border: 1px solid #232323;
    border-radius: 4px;
    outline: none;
    font-family: var(--font-mono), ui-monospace, monospace;
    font-size: 12px;
    line-height: 1.5;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  input:not([type='range']):focus, textarea:focus {
    border-color: #575757;
    box-shadow: 0 0 14px rgba(255,255,255,0.05);
  }
  input::placeholder, textarea::placeholder { color: #464646; }

  input[type='range'] {
    -webkit-appearance: none; appearance: none;
    background: transparent; border: none !important;
    cursor: pointer; height: 16px;
  }
  input[type='range']::-webkit-slider-runnable-track {
    height: 2px; background: #232323; border-radius: 1px;
  }
  /* Four-pointed ✦ thumb — the Shadow Slave mark. */
  input[type='range']::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 12px; height: 12px;
    background: #c4c4c4; margin-top: -5px;
    clip-path: polygon(50% 0%, 61% 39%, 100% 50%, 61% 61%, 50% 100%, 39% 61%, 0% 50%, 39% 39%);
    transition: background 0.15s ease;
  }
  input[type='range']:focus { outline: none; }
  input[type='range']:focus::-webkit-slider-thumb { background: #ffffff; }
  .range-vol::-webkit-slider-thumb { background: #575757; clip-path: none; border-radius: 50%; }
}

/* ─────────────────────────────────────────────────────────────────────────────
   BUTTONS — Cinzel, 4px radius, white-glow hovers. Crimson = danger only.
───────────────────────────────────────────────────────────────────────────── */

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 7px 14px; font-size: 11px; font-weight: 500;
  font-family: var(--font-display), Cinzel, serif;
  letter-spacing: 0.16em; text-transform: uppercase;
  border-radius: 4px; user-select: none; cursor: pointer;
  background: #111111;
  color: #c4c4c4;
  border: 1px solid #343434;
  transition: all 0.12s ease;
}
.btn:hover { border-color: #696969; color: #ffffff; box-shadow: 0 0 16px rgba(255,255,255,0.08); }
.btn:active { transform: scale(0.97); }
.btn:disabled { opacity: 0.25; cursor: not-allowed; }

/* Primary — bone-white invert. The brightest thing on screen. */
.btn-primary {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 20px; font-size: 11px; font-weight: 700;
  font-family: var(--font-display), Cinzel, serif;
  letter-spacing: 0.2em; text-transform: uppercase;
  border-radius: 4px; user-select: none; cursor: pointer;
  background: #e8e8e8;
  color: #000000;
  border: 1px solid #e8e8e8;
  box-shadow: 0 0 24px rgba(255,255,255,0.18);
  transition: background 0.12s ease, box-shadow 0.12s ease;
}
.btn-primary:hover { background: #ffffff; box-shadow: 0 0 32px rgba(255,255,255,0.28); }
.btn-primary:active { transform: scale(0.97); }
.btn-primary:disabled { opacity: 0.28; cursor: not-allowed; }

/* Danger — the only crimson interactive. */
.btn-danger {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 7px 14px; font-size: 11px; font-weight: 500;
  font-family: var(--font-display), Cinzel, serif;
  letter-spacing: 0.16em; text-transform: uppercase;
  border-radius: 4px; user-select: none; cursor: pointer;
  background: transparent;
  color: #b85560;
  border: 1px solid rgba(140,39,49,0.45);
  transition: all 0.12s ease;
}
.btn-danger:hover { background: #150b0c; border-color: #8c2731; color: #b85560; box-shadow: 0 0 10px rgba(140,39,49,0.3); }
.btn-danger:active { transform: scale(0.97); }
.btn-danger:disabled { opacity: 0.25; cursor: not-allowed; }

/* Secondary (VoiceMapper preview etc.) — same family as .btn. */
.btn-gold {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 7px 14px; font-size: 11px; font-weight: 500;
  font-family: var(--font-display), Cinzel, serif;
  letter-spacing: 0.16em; text-transform: uppercase;
  border-radius: 4px; user-select: none; cursor: pointer;
  background: transparent;
  color: #696969;
  border: 1px solid #343434;
  transition: all 0.12s ease;
}
.btn-gold:hover { color: #ffffff; border-color: #696969; box-shadow: 0 0 16px rgba(255,255,255,0.08); }
.btn-gold:active { transform: scale(0.97); }
.btn-gold:disabled { opacity: 0.25; cursor: not-allowed; }

/* Flat text filter tabs (queue bar, log controls). */
.btn-filter {
  display: inline-flex; align-items: center; justify-content: center; gap: 4px;
  padding: 6px 13px; font-size: 10px; font-weight: 500;
  letter-spacing: 0.18em; text-transform: uppercase;
  border-radius: 4px; user-select: none; cursor: pointer;
  background: transparent;
  color: #696969;
  border: none;
  transition: all 0.12s ease;
}
.btn-filter:hover { color: #c4c4c4; }
.btn-filter-active {
  background: #232323;
  color: #ffffff;
  text-shadow: 0 0 10px rgba(255,255,255,0.35);
}
.btn-filter-done-active { background: #232323; color: #e8e8e8; }
.btn-filter--blood { color: #b85560; }

/* ─────────────────────────────────────────────────────────────────────────────
   SURFACES
───────────────────────────────────────────────────────────────────────────── */

/* Command Deck panel — queue, inspector, player shells. */
.deck-card {
  background: rgba(10,10,10,0.82);
  border: 1px solid #232323;
  border-radius: 6px;
  box-shadow: 0 18px 50px rgba(0,0,0,0.6);
}

.glass-card {
  background: rgba(10,10,10,0.8);
  border: 1px solid #232323;
  border-radius: 6px;
}

.glass-panel {
  background: linear-gradient(180deg, rgba(255,255,255,0.015), transparent);
  border-bottom: 1px solid #1c1c1c;
}

/* VoiceMapper speaker cards. */
.memory-card {
  background: #111111;
  border: 1px solid #232323;
  border-radius: 4px;
  transition: border-color 0.15s ease;
}
.memory-card:hover { border-color: #464646; }
.memory-card--ready   { border-color: rgba(255,255,255,0.22); }
.memory-card--partial { border-color: #343434; }

/* ─────────────────────────────────────────────────────────────────────────────
   PROGRESS & DIVIDERS
───────────────────────────────────────────────────────────────────────────── */

.progress-track {
  height: 3px;
  background: #232323;
  border-radius: 1px;
  overflow: hidden;
  position: relative;
}
.progress-fill {
  display: block; height: 100%;
  background: #ffffff;
  box-shadow: 0 0 12px rgba(255,255,255,0.8);
  border-radius: 1px;
  transition: width 0.45s ease;
  position: relative; overflow: hidden;
}
/* Shimmer sweep across a live (determinate) fill. */
.progress-fill::after {
  content: '';
  position: absolute; inset: 0; width: 30%;
  background: linear-gradient(90deg, transparent, rgba(0,0,0,0.35), transparent);
  animation: spell-shimmer 2.2s infinite;
}
/* Indeterminate — diarize/assemble stages have no per-line progress. */
.progress-indeterminate::before {
  content: '';
  position: absolute; top: 0; bottom: 0; left: -30%; width: 30%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.55), transparent);
  animation: spell-scan 1.6s ease-in-out infinite;
}
@keyframes spell-shimmer {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(420%); }
}
@keyframes spell-scan {
  0%   { left: -30%; }
  100% { left: 100%; }
}

.weaver-thread {
  height: 1px;
  background: linear-gradient(to right,
    transparent 0%, #232323 20%, #464646 50%, #232323 80%, transparent 100%);
}

/* Inspector live-stage halo. */
.stage-glow {
  background: radial-gradient(ellipse 90% 100% at 50% 0%, #1b1b1b 0%, transparent 70%);
}

/* ─────────────────────────────────────────────────────────────────────────────
   DREAM REALM — vignette + giant ghost ✦ watermark (spec §2)
───────────────────────────────────────────────────────────────────────────── */

.dream-realm { position: relative; }
.dream-realm::before {
  content: '✦';
  position: fixed; right: -60px; bottom: -90px;
  font-size: 420px; line-height: 1;
  color: #070707;
  transform: rotate(12deg);
  pointer-events: none; z-index: 0;
}
.dream-realm::after {
  content: '';
  position: fixed; inset: 0;
  pointer-events: none; z-index: 40;
  background: radial-gradient(ellipse 120% 90% at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%);
}
.dream-realm > * { position: relative; z-index: 1; }

/* ─────────────────────────────────────────────────────────────────────────────
   SPELL TOASTS — [ bracketed system messages ]. z-50 keeps them above the
   vignette layer (z-40).
───────────────────────────────────────────────────────────────────────────── */

.spell-toast {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 14px;
  max-width: 360px;
  background: rgba(0,0,0,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid #232323;
  border-left-width: 2px;
  border-radius: 4px;
  font-family: var(--font-mono), ui-monospace, monospace;
  font-size: 11px;
  line-height: 1.55;
}
/* Warnings are urgent-but-not-blood: bright white, breathing. */
.spell-toast--warn    { border-left-color: #ffffff; color: #e8e8e8; animation: breathe 2.4s ease-in-out infinite; }
.spell-toast--crimson { border-left-color: #8c2731; color: #b85560; }
.spell-toast--chrome  { border-left-color: #c4c4c4; color: #e8e8e8; }
.spell-toast .spell-bracket { opacity: 0.45; user-select: none; }
@keyframes breathe {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.55; }
}

/* ─────────────────────────────────────────────────────────────────────────────
   LOG / PLAYER HELPERS
───────────────────────────────────────────────────────────────────────────── */

.log-scanlines { position: relative; background: #050505; }
.log-scanlines::before {
  content: '';
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    0deg, transparent 0px, transparent 3px,
    rgba(0,0,0,0.12) 3px, rgba(0,0,0,0.12) 4px);
  pointer-events: none; z-index: 1;
}
.log-scanlines > * { position: relative; z-index: 2; }

.cv-auto { content-visibility: auto; contain-intrinsic-size: auto 64px; }

.equalizer { display: inline-flex; align-items: flex-end; gap: 2px; height: 12px; }
.equalizer span {
  width: 2px; height: 100%;
  background: #ffffff;
  box-shadow: 0 0 6px rgba(255,255,255,0.6);
  transform-origin: bottom;
  animation: equalize 0.9s ease-in-out infinite;
}
.equalizer span:nth-child(2) { animation-delay: 0.25s; }
.equalizer span:nth-child(3) { animation-delay: 0.5s;  }
.equalizer--paused span { animation-play-state: paused; opacity: 0.4; }

/* ─────────────────────────────────────────────────────────────────────────────
   MISC + COMPONENT PRIMITIVES
───────────────────────────────────────────────────────────────────────────── */

.chip {
  display: inline-flex; align-items: center;
  padding: 2px 8px; font-size: 10px; font-weight: 500;
  border-radius: 4px;
  background: transparent;
  color: #696969;
  border: 1px solid #232323;
  letter-spacing: 0.07em;
}

@layer components {
  .label {
    @apply text-[10px] font-medium uppercase text-ink-muted;
    font-family: var(--font-mono), ui-monospace, monospace;
    letter-spacing: 0.18em;
  }

  .input {
    @apply w-full px-3 py-2.5 text-xs text-ink-primary focus:outline-none;
    font-family: var(--font-mono), ui-monospace, monospace;
    background: #111111;
  }

  .divider { border-top: 1px solid #232323; }

  /* Status mark — four-pointed ✦ via clip-path (used by legacy status dots). */
  .status-dot {
    @apply w-2 h-2 flex-shrink-0;
    clip-path: polygon(50% 0%, 61% 39%, 100% 50%, 61% 61%, 50% 100%, 39% 61%, 0% 50%, 39% 39%);
    border-radius: 0;
  }

  .tech {
    font-family: var(--font-mono), ui-monospace, monospace;
    letter-spacing: 0.04em;
  }
}
```

- [ ] **Step 4: Fix the Toasts tone for the renamed class NOW (avoids a broken intermediate state)**

`page.tsx` currently calls `pushToast('gold', …)` for `vram_warning`, and `Toasts.tsx` maps `gold → spell-toast--gold` which no longer exists. In `ui/components/Toasts.tsx` change:

```ts
export type ToastTone = 'warn' | 'crimson' | 'chrome'
```

```ts
const TONE_CLASS: Record<ToastTone, string> = {
  warn:    'spell-toast--warn',
  crimson: 'spell-toast--crimson',
  chrome:  'spell-toast--chrome',
}

const TONE_SIGIL: Record<ToastTone, string> = {
  warn:    '!',
  crimson: '✗',
  chrome:  '✓',
}
```

And in `ui/app/page.tsx:222-224` change the vram_warning handler's tone:

```ts
    if (e.type === 'vram_warning') {
      pushToast('warn', `The Spell warns: VRAM ${e.used_mb} MB exceeds the ${e.threshold_mb} MB barrier.`)
    }
```

- [ ] **Step 5: Gates**

Run: `cd ui; npm run typecheck; npm test; npm run build`
Expected: all clean. The old UI now renders in grayscale — that's correct; it lives only until Task 10.

- [ ] **Step 6: Commit**

```powershell
git add ui/app/layout.tsx ui/tailwind.config.ts ui/app/globals.css ui/components/Toasts.tsx ui/app/page.tsx
git commit -m "feat(ui): Nightmare Spell grayscale theme — tokens, fonts, toast tones"
```

---

### Task 5: `lib/format.ts` helpers

**Files:**
- Create: `ui/lib/format.ts`
- Test: `ui/tests/format.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `ui/tests/format.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { formatEta, formatMB, parseChapterError } from '@/lib/format'

describe('formatEta', () => {
  it('formats hours and minutes', () => {
    expect(formatEta(2 * 3600 + 5 * 60)).toBe('~2h 5m left')
  })
  it('formats minutes only', () => {
    expect(formatEta(240)).toBe('~4m left')
  })
  it('returns empty for non-positive or non-finite', () => {
    expect(formatEta(0)).toBe('')
    expect(formatEta(Number.NaN)).toBe('')
  })
})

describe('formatMB', () => {
  it('formats bytes as MB with one decimal', () => {
    expect(formatMB(22_452_000)).toBe('21.4 MB')
  })
  it('returns empty for null', () => {
    expect(formatMB(null)).toBe('')
  })
})

describe('parseChapterError', () => {
  it('extracts the failed stage prefix', () => {
    expect(parseChapterError('[failed_stage:synthesize] CUDA OOM at line 31')).toEqual({
      stage: 'synthesize',
      detail: 'CUDA OOM at line 31',
    })
  })
  it('handles messages without a stage prefix', () => {
    expect(parseChapterError('boom')).toEqual({ stage: null, detail: 'boom' })
  })
  it('handles null', () => {
    expect(parseChapterError(null)).toEqual({ stage: null, detail: 'Unknown error' })
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ui; npm test`
Expected: FAIL — cannot resolve `@/lib/format`.

- [ ] **Step 3: Implement**

Create `ui/lib/format.ts` (`formatEta` body is moved verbatim from `StatsBar.tsx:21-28`):

```ts
/** "~2h 5m left" / "~4m left" — ETA from seconds; empty when unknowable. */
export function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `~${h}h ${m}m left`
  if (m > 0) return `~${m}m left`
  return '~1m left'
}

/** "21.4 MB" — chapter file sizes in the queue sub-line. */
export function formatMB(bytes: number | null): string {
  if (bytes == null) return ''
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}

/** Splits the backend's "[failed_stage:X] detail" error format. */
export function parseChapterError(
  msg: string | null,
): { stage: string | null; detail: string } {
  if (!msg) return { stage: null, detail: 'Unknown error' }
  const m = /^\[failed_stage:(\w+)\]\s*/.exec(msg)
  return m ? { stage: m[1], detail: msg.slice(m[0].length) } : { stage: null, detail: msg }
}
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `cd ui; npm test`
Expected: PASS.

```powershell
git add ui/lib/format.ts ui/tests/format.test.ts
git commit -m "feat(ui): format helpers — formatEta (moved), formatMB, parseChapterError"
```

---

### Task 6: `usePipelineState` — the SSE reducer hook

**Files:**
- Create: `ui/hooks/usePipelineState.ts`
- Test: `ui/tests/usePipelineState.test.ts`

- [ ] **Step 1: Write the failing reducer tests**

Create `ui/tests/usePipelineState.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  pipelineReducer, initialPipelineState, type PipelineUIState,
} from '@/hooks/usePipelineState'
import type { SSEEvent } from '@/lib/types'

const ev = (partial: Partial<SSEEvent> & { type: string }): SSEEvent =>
  ({ ts: 0, ...partial })

const sse = (s: PipelineUIState, e: SSEEvent) =>
  pipelineReducer(s, { kind: 'sse', event: e, now: 1000 })

describe('pipelineReducer', () => {
  it('tracks a chapter through synthesis and exposes the live line', () => {
    let s = sse(initialPipelineState, ev({ type: 'pipeline_start' }))
    expect(s.startedAt).toBe(1000)
    s = sse(s, ev({ type: 'chapter_start', chapter_id: 7 }))
    s = sse(s, ev({ type: 'stage_start', chapter_id: 7, stage: 'synthesize' }))
    s = sse(s, ev({
      type: 'tts_progress', chapter_id: 7, lines_done: 3, lines_total: 44,
      text: 'Sunny frowned.', speaker: 'Sunny', emotion: 'tense',
    }))
    expect(s.activeChId).toBe(7)
    expect(s.activeStage).toBe('synthesize')
    expect(s.ttsProgress[7]).toEqual({ done: 3, total: 44 })
    expect(s.liveLine).toEqual({ text: 'Sunny frowned.', speaker: 'Sunny', emotion: 'tense' })

    s = sse(s, ev({ type: 'chapter_done', chapter_id: 7 }))
    expect(s.activeChId).toBeNull()
    expect(s.liveLine).toBeNull()
    expect(s.refreshNonce).toBe(1)
  })

  it('keeps the previous live line when a tts_progress event has no text', () => {
    let s = sse(initialPipelineState, ev({
      type: 'tts_progress', chapter_id: 1, lines_done: 1, lines_total: 9,
      text: 'First.', speaker: 'Narrator', emotion: 'neutral',
    }))
    s = sse(s, ev({ type: 'tts_progress', chapter_id: 1, lines_done: 2, lines_total: 9 }))
    expect(s.liveLine?.text).toBe('First.')
    expect(s.ttsProgress[1]).toEqual({ done: 2, total: 9 })
  })

  it('chapter_error raises a crimson toast and bumps refreshNonce', () => {
    const s = sse(initialPipelineState, ev({ type: 'chapter_error', chapter_id: 3, error: 'CUDA OOM' }))
    expect(s.toasts).toHaveLength(1)
    expect(s.toasts[0].tone).toBe('crimson')
    expect(s.toasts[0].message).toContain('CUDA OOM')
    expect(s.refreshNonce).toBe(1)
  })

  it('pipeline_done sets status complete with a chrome toast', () => {
    const s = sse(initialPipelineState, ev({ type: 'pipeline_done', success: 12 }))
    expect(s.pipeStatus).toBe('complete')
    expect(s.toasts[0].tone).toBe('chrome')
  })

  it('vram_warning raises a warn toast and records vramMb', () => {
    const s = sse(initialPipelineState, ev({ type: 'vram_warning', used_mb: 7900, threshold_mb: 1500 }))
    expect(s.toasts[0].tone).toBe('warn')
    expect(s.vramMb).toBe(7900)
  })

  it('caps the event log at 500 entries', () => {
    let s = initialPipelineState
    for (let i = 0; i < 510; i++) s = sse(s, ev({ type: 'stage_done', ts: i }))
    expect(s.events).toHaveLength(500)
  })

  it('supports manual toasts and dismissal', () => {
    let s = pipelineReducer(initialPipelineState, { kind: 'toast', tone: 'crimson', message: 'Failed to stop' })
    const id = s.toasts[0].id
    s = pipelineReducer(s, { kind: 'dismiss-toast', id })
    expect(s.toasts).toHaveLength(0)
  })

  it('tracks connection and explicit status changes', () => {
    let s = pipelineReducer(initialPipelineState, { kind: 'connection', connected: false })
    expect(s.connected).toBe(false)
    s = pipelineReducer(s, { kind: 'set-status', status: 'running' })
    expect(s.pipeStatus).toBe('running')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ui; npm test`
Expected: FAIL — cannot resolve `@/hooks/usePipelineState`.

- [ ] **Step 3: Implement the hook**

Create `ui/hooks/usePipelineState.ts`:

```ts
'use client'
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { useSSE } from '@/hooks/useSSE'
import type { SSEEvent, PipelineStatusResponse } from '@/lib/types'
import type { Toast, ToastTone } from '@/components/Toasts'

export type PipeStatus = PipelineStatusResponse['status']
export type Stage = 'diarize' | 'synthesize' | 'assemble'

export interface LiveLine { text: string; speaker: string; emotion: string }

export interface PipelineUIState {
  pipeStatus: PipeStatus
  events: SSEEvent[]
  activeChId: number | null
  activeStage: Stage | null
  ttsProgress: Record<number, { done: number; total: number }>
  liveLine: LiveLine | null
  startedAt: number | null
  connected: boolean
  vramMb: number | null
  toasts: Toast[]
  nextToastId: number
  /** Bumped on chapter/pipeline boundaries — the hook refetches snapshots. */
  refreshNonce: number
}

export type PipelineAction =
  | { kind: 'sse'; event: SSEEvent; now: number }
  | { kind: 'set-status'; status: PipeStatus }
  | { kind: 'connection'; connected: boolean }
  | { kind: 'toast'; tone: ToastTone; message: string }
  | { kind: 'dismiss-toast'; id: number }
  | { kind: 'clear-log' }

export const initialPipelineState: PipelineUIState = {
  pipeStatus: 'idle',
  events: [],
  activeChId: null,
  activeStage: null,
  ttsProgress: {},
  liveLine: null,
  startedAt: null,
  connected: true,
  vramMb: null,
  toasts: [],
  nextToastId: 1,
  refreshNonce: 0,
}

const MAX_EVENTS = 500
const MAX_TOASTS = 5

function withToast(s: PipelineUIState, tone: ToastTone, message: string): PipelineUIState {
  const toast: Toast = { id: s.nextToastId, tone, message }
  return {
    ...s,
    toasts: [...s.toasts.slice(-(MAX_TOASTS - 1)), toast],
    nextToastId: s.nextToastId + 1,
  }
}

function clearActive(s: PipelineUIState): PipelineUIState {
  return { ...s, activeChId: null, activeStage: null, liveLine: null }
}

export function pipelineReducer(s: PipelineUIState, a: PipelineAction): PipelineUIState {
  switch (a.kind) {
    case 'set-status':   return { ...s, pipeStatus: a.status }
    case 'connection':   return { ...s, connected: a.connected }
    case 'toast':        return withToast(s, a.tone, a.message)
    case 'dismiss-toast': return { ...s, toasts: s.toasts.filter(t => t.id !== a.id) }
    case 'clear-log':    return { ...s, events: [] }
    case 'sse': {
      const e = a.event
      let next: PipelineUIState = { ...s, events: [...s.events.slice(-(MAX_EVENTS - 1)), e] }
      switch (e.type) {
        case 'pipeline_start':
          return { ...next, startedAt: a.now, ttsProgress: {}, liveLine: null }
        case 'chapter_start':
          return { ...next, activeChId: e.chapter_id ?? null, activeStage: null, liveLine: null }
        case 'stage_start':
          if (typeof e.stage !== 'string') return next
          return {
            ...next,
            activeStage: e.stage as Stage,
            liveLine: e.stage === 'synthesize' ? next.liveLine : null,
          }
        case 'tts_progress': {
          if (e.chapter_id == null) return next
          const liveLine = typeof e.text === 'string'
            ? { text: e.text, speaker: String(e.speaker ?? ''), emotion: String(e.emotion ?? '') }
            : next.liveLine
          return {
            ...next,
            activeChId: e.chapter_id,
            liveLine,
            ttsProgress: {
              ...next.ttsProgress,
              [e.chapter_id]: { done: e.lines_done ?? 0, total: e.lines_total ?? 0 },
            },
          }
        }
        case 'chapter_done':
          return { ...clearActive(next), refreshNonce: next.refreshNonce + 1 }
        case 'chapter_error':
          next = withToast(next, 'crimson',
            `Chapter ${e.chapter_id ?? '?'} has fallen — ${String(e.error ?? 'unknown error').slice(0, 120)}`)
          return { ...clearActive(next), refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_done':
          next = withToast(next, 'chrome',
            `Congratulations, Sleeper. ${e.success ?? 0} chapters transcribed.`)
          return { ...clearActive(next), pipeStatus: 'complete', refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_stopped':
          return { ...clearActive(next), pipeStatus: 'stopped', refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_error':
          next = withToast(next, 'crimson',
            `The Nightmare collapsed: ${String(e.error ?? 'unknown error').slice(0, 120)}`)
          return { ...next, pipeStatus: 'error' }
        case 'vram_warning':
          next = withToast(next, 'warn',
            `The Spell warns: VRAM ${e.used_mb} MB exceeds the ${e.threshold_mb} MB barrier.`)
          return { ...next, vramMb: typeof e.used_mb === 'number' ? e.used_mb : next.vramMb }
        default:
          return next
      }
    }
  }
}

/**
 * State of record for the pipeline UI. Pure reducer over SSE events;
 * `onRefresh` fires after chapter/pipeline boundaries so the page can
 * refetch chapter + progress snapshots (the self-heal sync model).
 */
export function usePipelineState(onRefresh: () => void) {
  const [state, dispatch] = useReducer(pipelineReducer, initialPipelineState)
  const onRefreshRef = useRef(onRefresh)
  onRefreshRef.current = onRefresh

  useEffect(() => {
    if (state.refreshNonce > 0) onRefreshRef.current()
  }, [state.refreshNonce])

  const handleSSE = useCallback(
    (e: SSEEvent) => dispatch({ kind: 'sse', event: e, now: Date.now() }), [])
  const handleConnection = useCallback(
    (connected: boolean) => dispatch({ kind: 'connection', connected }), [])

  useSSE(state.pipeStatus === 'running' || state.pipeStatus === 'paused', handleSSE, handleConnection)

  return { state, dispatch }
}
```

- [ ] **Step 4: Run to verify pass, gates, commit**

Run: `cd ui; npm test; npm run typecheck`
Expected: all pass.

```powershell
git add ui/hooks/usePipelineState.ts ui/tests/usePipelineState.test.ts
git commit -m "feat(ui): usePipelineState — pure SSE reducer hook with toasts and refresh nonce"
```

---

### Task 7: CommandStrip (header)

**Files:**
- Create: `ui/components/CommandStrip.tsx`
- Test: `ui/tests/CommandStrip.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `ui/tests/CommandStrip.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import CommandStrip from '@/components/CommandStrip'
import type { Progress } from '@/lib/types'

const progress: Progress = {
  total: 2190, pending: 339, diarized: 0, tts_done: 0, assembled: 0,
  complete: 1849, error: 1, pct_complete: 84,
}

const base = {
  connected: true,
  progress,
  activeStage: null,
  eta: '~4h 12m left',
  vramMb: 7900,
  onStart: vi.fn(), onPause: vi.fn(), onResume: vi.fn(), onStop: vi.fn(),
}

describe('CommandStrip', () => {
  it('shows RUN when startable and chapter counts', () => {
    render(<CommandStrip {...base} pipeStatus="idle" canStart />)
    expect(screen.getByRole('button', { name: /run/i })).toBeEnabled()
    expect(screen.getByText('1849')).toBeInTheDocument()
    expect(screen.getByText(/2190/)).toBeInTheDocument()
  })

  it('shows PAUSE and STOP while running, with the stage label', () => {
    render(<CommandStrip {...base} pipeStatus="running" activeStage="synthesize" canStart={false} />)
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument()
    expect(screen.getByText(/synthesizing/i)).toBeInTheDocument()
  })

  it('shows LINK SEVERED when running but disconnected', () => {
    render(<CommandStrip {...base} pipeStatus="running" connected={false} canStart={false} />)
    expect(screen.getByText(/link severed/i)).toBeInTheDocument()
  })

  it('shows RESUME while paused', () => {
    render(<CommandStrip {...base} pipeStatus="paused" canStart={false} />)
    expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure** — `cd ui; npm test` → cannot resolve component.

- [ ] **Step 3: Implement**

Create `ui/components/CommandStrip.tsx`:

```tsx
'use client'
import type { Progress } from '@/lib/types'
import type { PipeStatus, Stage } from '@/hooks/usePipelineState'

const STATUS_LABEL: Record<PipeStatus, string> = {
  idle: 'Dormant', running: 'Running', paused: 'Suspended',
  complete: 'Complete', stopped: 'Stopped', error: 'Error',
}

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving', synthesize: 'Synthesizing', assemble: 'Binding',
}

interface Props {
  pipeStatus: PipeStatus
  connected: boolean
  progress: Progress | null
  activeStage: Stage | null
  eta: string
  vramMb: number | null
  canStart: boolean
  onStart: () => void
  onPause: () => void
  onResume: () => void
  onStop: () => void
}

function Stat({ value, label, live = false }: {
  value: React.ReactNode; label: string; live?: boolean
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={`font-mono text-sm tabular-nums ${
        live ? 'text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.5)]' : 'text-ink-primary'
      }`}>
        {value}
      </span>
      <span className="text-[9px] tracking-[0.18em] text-spell-g5 uppercase">{label}</span>
    </div>
  )
}

const Sep = () => <span className="w-px h-[18px] bg-spell-g2" aria-hidden />

export default function CommandStrip({
  pipeStatus, connected, progress, activeStage, eta, vramMb, canStart,
  onStart, onPause, onResume, onStop,
}: Props) {
  const running  = pipeStatus === 'running'
  const paused   = pipeStatus === 'paused'
  const severed  = (running || paused) && !connected

  const liveLabel = severed
    ? 'Link severed'
    : running
      ? (activeStage ? STAGE_LABEL[activeStage] : 'Running')
      : STATUS_LABEL[pipeStatus]

  return (
    <header className="glass-panel flex items-center gap-7 px-6 pt-5 pb-4 flex-shrink-0">
      <div className="select-none">
        <h1 className="font-display font-bold text-[21px] leading-none tracking-[6px] text-ink-primary
                       animate-flicker [text-shadow:0_0_18px_rgba(255,255,255,0.22),0_0_60px_rgba(255,255,255,0.08)]">
          NIGHTMARE SPELL
        </h1>
        <span className="block mt-1 text-[9px] tracking-[3.5px] uppercase text-spell-g5">
          Shadow Slave · Audiobook Forge
        </span>
      </div>

      <div className="flex gap-2.5">
        {canStart && (
          <button className="btn-primary" onClick={onStart}>▶ Run</button>
        )}
        {running && <button className="btn" onClick={onPause}>‖ Pause</button>}
        {paused  && <button className="btn-primary" onClick={onResume}>▶ Resume</button>}
        {(running || paused) && <button className="btn-danger" onClick={onStop}>■ Stop</button>}
      </div>

      <div className="ml-auto flex items-center gap-5">
        <div className="flex items-baseline gap-2">
          <span className={`text-sm leading-none ${
            severed
              ? 'text-spell-g5'
              : running
                ? 'text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.5)]'
                : 'text-spell-g6'
          }`} aria-hidden>✦</span>
          <span className="text-[9px] tracking-[0.18em] uppercase text-spell-g5">{liveLabel}</span>
        </div>
        {progress && (
          <>
            <Sep />
            <Stat
              value={<>
                <span className="text-ink-primary">{progress.complete}</span>
                <span className="text-spell-g5">∕{progress.total}</span>
              </>}
              label="Chapters"
            />
          </>
        )}
        {eta && (<><Sep /><Stat value={eta.replace(' left', '')} label="ETA" /></>)}
        <Sep />
        <Stat value={vramMb != null ? `${(vramMb / 1024).toFixed(1)}G` : '—'} label="VRAM" />
      </div>
    </header>
  )
}
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `cd ui; npm test; npm run typecheck` → PASS.

```powershell
git add ui/components/CommandStrip.tsx ui/tests/CommandStrip.test.tsx
git commit -m "feat(ui): CommandStrip header — brand, transport controls, live stats"
```

---

### Task 8: ChapterQueue

**Files:**
- Create: `ui/components/ChapterQueue.tsx`
- Test: `ui/tests/ChapterQueue.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `ui/tests/ChapterQueue.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ChapterQueue from '@/components/ChapterQueue'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1, project_id: 1, chapter_index: 0, title: 'Chapter One',
    status: 'pending', total_chunks: 1, total_lines: 44,
    output_audio_path: null, output_file_size_bytes: null,
    processing_seconds: null, error_message: null, updated_at: '',
    ...overrides,
  }
}

const chapters = [
  makeChapter({ id: 1, chapter_index: 0, title: 'What Lies Beneath', status: 'complete', output_audio_path: 'x.mp3', output_file_size_bytes: 24_200_000 }),
  makeChapter({ id: 2, chapter_index: 1, title: 'Cold Light', status: 'error', error_message: '[failed_stage:synthesize] CUDA OOM at line 31' }),
  makeChapter({ id: 3, chapter_index: 2, title: 'Sleepless', status: 'pending' }),
]

const base = {
  chapters,
  activeChapterId: null,
  activeStage: null,
  ttsProgress: {},
  selectedId: null,
  onSelect: vi.fn(),
  playingChapterId: null,
  playerPlaying: false,
  onPlay: vi.fn(),
  onChanged: vi.fn(),
}

describe('ChapterQueue', () => {
  it('renders one row per chapter with status sub-lines', () => {
    render(<ChapterQueue {...base} />)
    expect(screen.getByText('What Lies Beneath')).toBeInTheDocument()
    expect(screen.getByText(/23\.1 MB/)).toBeInTheDocument()
    expect(screen.getByText(/Failed at synthesize/)).toBeInTheDocument()
    expect(screen.getByText(/CUDA OOM/)).toBeInTheDocument()
  })

  it('filters to failed chapters', () => {
    render(<ChapterQueue {...base} />)
    fireEvent.click(screen.getByRole('button', { name: /failed/i }))
    expect(screen.getByText('Cold Light')).toBeInTheDocument()
    expect(screen.queryByText('Sleepless')).not.toBeInTheDocument()
  })

  it('searches by title', () => {
    render(<ChapterQueue {...base} />)
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'sleep' } })
    expect(screen.getByText('Sleepless')).toBeInTheDocument()
    expect(screen.queryByText('Cold Light')).not.toBeInTheDocument()
  })

  it('shows live synthesis progress on the running row', () => {
    render(<ChapterQueue
      {...base}
      activeChapterId={3}
      activeStage="synthesize"
      ttsProgress={{ 3: { done: 27, total: 44 } }}
    />)
    expect(screen.getByText(/27\s*∕\s*44/)).toBeInTheDocument()
  })

  it('routes play to the global player and selection to the inspector', () => {
    const onPlay = vi.fn(); const onSelect = vi.fn()
    render(<ChapterQueue {...base} onPlay={onPlay} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Sleepless'))
    expect(onSelect).toHaveBeenCalledWith(3)
    fireEvent.click(screen.getByRole('button', { name: /play chapter 1/i }))
    expect(onPlay).toHaveBeenCalledWith(1)
  })
})
```

Note on `23.1 MB`: `24_200_000 / 1_048_576 = 23.08… → "23.1 MB"`.

- [ ] **Step 2: Run to verify failure** — `cd ui; npm test` → cannot resolve component.

- [ ] **Step 3: Implement**

Create `ui/components/ChapterQueue.tsx`:

```tsx
'use client'
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import ConfirmButton from '@/components/ConfirmButton'
import { deleteChapterAudio, resetChapter } from '@/lib/api'
import { formatMB, parseChapterError } from '@/lib/format'
import type { Chapter, ChapterStatus } from '@/lib/types'
import type { Stage } from '@/hooks/usePipelineState'

type Filter = 'all' | 'pending' | 'complete' | 'failed'
const RENDER_CHUNK = 120

const STATUS_SUB: Record<ChapterStatus, string> = {
  pending: 'Pending', diarized: 'Diarized', tts_done: 'Synthesized',
  assembled: 'Assembled', complete: 'Complete', error: 'Failed',
}

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving the dream', synthesize: 'Synthesizing', assemble: 'Binding echoes',
}

const MARK_CLASS: Record<ChapterStatus, string> = {
  pending:   'text-spell-g3',
  diarized:  'text-spell-g5',
  tts_done:  'text-spell-g6',
  assembled: 'text-spell-g6',
  complete:  'text-spell-g6',
  error:     'text-blood-text [text-shadow:0_0_10px_rgba(140,39,49,0.6)]',
}

interface RowProps {
  chapter: Chapter
  isRunning: boolean
  activeStage: Stage | null
  ttsProg?: { done: number; total: number }
  selected: boolean
  isPlaying: boolean
  playerPlaying: boolean
  onSelect: (id: number) => void
  onPlay: (id: number) => void
  onChanged: () => void
}

const QueueRow = memo(function QueueRow({
  chapter, isRunning, activeStage, ttsProg, selected, isPlaying, playerPlaying,
  onSelect, onPlay, onChanged,
}: RowProps) {
  const num = String(chapter.chapter_index + 1)
  const failed = chapter.status === 'error'
  const complete = chapter.status === 'complete'

  if (isRunning) {
    const pct = ttsProg && ttsProg.total > 0 ? Math.round((ttsProg.done / ttsProg.total) * 100) : 0
    const synth = activeStage === 'synthesize'
    return (
      <div className="cv-auto rounded border border-spell-g6 bg-gradient-to-b from-[#1c1c1c] to-spell-g1
                      p-[15px] flex items-center gap-[15px] animate-glowpulse"
           data-chapter-row={chapter.id}>
        <span className="font-mono text-xs w-[42px] text-right flex-none text-ink-hot [text-shadow:0_0_10px_rgba(255,255,255,0.5)]">
          {num}
        </span>
        <span className="flex-none text-[11px] leading-none text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.7)]" aria-hidden>✦</span>
        <div className="flex-1 min-w-0">
          <div className="font-display text-[14.5px] tracking-[1.5px] text-ink-hot truncate [text-shadow:0_0_14px_rgba(255,255,255,0.3)]">
            {chapter.title}
          </div>
          <div className="flex items-center gap-2 mt-1 text-[10.5px] text-spell-g7">
            <span className="equalizer" aria-hidden><span /><span /><span /></span>
            <b className="text-ink-primary font-medium">
              {activeStage ? STAGE_LABEL[activeStage] : 'Processing'}
            </b>
            {synth && ttsProg && (
              <span>· line <b className="text-ink-primary">{ttsProg.done}∕{ttsProg.total}</b></span>
            )}
          </div>
          <div className={`progress-track mt-2 ${synth ? '' : 'progress-indeterminate'}`}>
            {synth && <i className="progress-fill" style={{ width: `${pct}%` }} />}
          </div>
        </div>
      </div>
    )
  }

  const err = failed ? parseChapterError(chapter.error_message) : null

  return (
    <div
      className={`cv-auto group rounded border px-[15px] py-2.5 flex items-center gap-[15px] cursor-pointer
                  transition-[transform,border-color] duration-150 hover:translate-x-[3px]
                  ${failed
                    ? 'bg-blood-bg border-[#33141a]'
                    : 'bg-spell-g1 border-[#1d1d1d] hover:border-spell-g4 hover:bg-[#151515]'}
                  ${selected ? '!border-spell-g6' : ''}`}
      data-chapter-row={chapter.id}
      onClick={() => onSelect(chapter.id)}
    >
      <span className="font-mono text-xs w-[42px] text-right flex-none text-spell-g6">{num}</span>
      <span className={`flex-none text-[11px] leading-none ${MARK_CLASS[chapter.status]}`} aria-hidden>✦</span>
      <div className="flex-1 min-w-0">
        <div className={`font-medium truncate ${
          failed ? 'text-blood-text' : complete ? 'text-ink-primary' : 'text-ink-secondary'
        }`}>
          {chapter.title}
        </div>
        <div className={`text-[10.5px] mt-px truncate ${failed ? 'text-[#8d4a51]' : 'text-spell-g6'}`}>
          {failed && err
            ? <>Failed at {err.stage ?? 'unknown stage'} — {err.detail}</>
            : complete
              ? <>Complete{chapter.output_file_size_bytes != null && (
                  <> · <span className="font-mono">{formatMB(chapter.output_file_size_bytes)}</span></>
                )}</>
              : STATUS_SUB[chapter.status]}
        </div>
      </div>

      {isPlaying && (
        <span className={`equalizer flex-none ${playerPlaying ? '' : 'equalizer--paused'}`} aria-hidden>
          <span /><span /><span />
        </span>
      )}

      <div className="hidden group-hover:flex gap-1.5 flex-none" onClick={e => e.stopPropagation()}>
        {complete && chapter.output_audio_path != null && (
          <button
            className="btn !p-0 w-[27px] h-[27px] text-[11px]"
            onClick={() => onPlay(chapter.id)}
            aria-label={`Play chapter ${num}`}
            title="Play in the Echo player"
          >▶</button>
        )}
        {(complete || failed) && (
          <ConfirmButton
            className="btn !p-0 w-[27px] h-[27px] text-[11px]"
            confirmClassName="btn !px-2 h-[27px] text-[9px]"
            confirmLabel={failed ? 'Retry?' : 'Redo?'}
            onConfirm={async () => { await resetChapter(chapter.id); onChanged() }}
            ariaLabel={failed ? `Retry chapter ${num}` : `Redo chapter ${num}`}
            title="Reset and re-run this chapter"
          >↻</ConfirmButton>
        )}
        {complete && (
          <ConfirmButton
            className="btn-danger !p-0 w-[27px] h-[27px] text-[11px]"
            confirmClassName="btn-danger !px-2 h-[27px] text-[9px]"
            confirmLabel="Delete?"
            onConfirm={async () => { await deleteChapterAudio(chapter.id); onChanged() }}
            ariaLabel={`Delete audio for chapter ${num}`}
            title="Delete audio from disk"
          >✕</ConfirmButton>
        )}
      </div>
    </div>
  )
})

interface Props {
  chapters: Chapter[]
  activeChapterId: number | null
  activeStage: Stage | null
  ttsProgress: Record<number, { done: number; total: number }>
  selectedId: number | null
  onSelect: (id: number) => void
  playingChapterId: number | null
  playerPlaying: boolean
  onPlay: (id: number) => void
  /** Fired after retry/redo/delete so the page refetches chapters. */
  onChanged: () => void
}

export default function ChapterQueue({
  chapters, activeChapterId, activeStage, ttsProgress, selectedId, onSelect,
  playingChapterId, playerPlaying, onPlay, onChanged,
}: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query,  setQuery]  = useState('')
  const [limit,  setLimit]  = useState(RENDER_CHUNK)
  const sentinelRef = useRef<HTMLDivElement>(null)

  const counts = useMemo(() => {
    let complete = 0, failed = 0
    for (const c of chapters) {
      if (c.status === 'complete') complete++
      else if (c.status === 'error') failed++
    }
    return { all: chapters.length, complete, failed, pending: chapters.length - complete - failed }
  }, [chapters])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return chapters.filter(c => {
      if (filter === 'complete' && c.status !== 'complete') return false
      if (filter === 'failed'   && c.status !== 'error')    return false
      if (filter === 'pending'  && (c.status === 'complete' || c.status === 'error')) return false
      if (q && !c.title.toLowerCase().includes(q) && !String(c.chapter_index + 1).includes(q)) return false
      return true
    })
  }, [chapters, filter, query])

  // Incremental render — grow the window as the sentinel scrolls into view.
  // jsdom has no IntersectionObserver: render everything there (tests).
  useEffect(() => { setLimit(RENDER_CHUNK) }, [filter, query])
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') { setLimit(Number.MAX_SAFE_INTEGER); return }
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) setLimit(l => l + RENDER_CHUNK)
    })
    io.observe(el)
    return () => io.disconnect()
  }, [visible.length, limit])

  const FILTERS: { key: Filter; label: string; count: number; blood?: boolean }[] = [
    { key: 'all',      label: 'All',      count: counts.all },
    { key: 'pending',  label: 'Pending',  count: counts.pending },
    { key: 'complete', label: 'Complete', count: counts.complete },
    { key: 'failed',   label: 'Failed',   count: counts.failed, blood: true },
  ]

  return (
    <section className="deck-card flex-[1.8] flex flex-col min-w-0 overflow-hidden">
      <div className="flex items-center gap-1.5 px-[15px] py-[13px] border-b border-[#1a1a1a]">
        {FILTERS.map(f => (
          <button
            key={f.key}
            className={`btn-filter ${filter === f.key ? 'btn-filter-active' : ''} ${f.blood ? 'btn-filter--blood' : ''}`}
            onClick={() => setFilter(f.key)}
            aria-pressed={filter === f.key}
          >
            {f.label}<b className="font-mono font-normal opacity-70 ml-1">{f.count}</b>
          </button>
        ))}
        <input
          className="ml-auto w-[200px] !py-[7px] !px-[13px]"
          placeholder="Search chapters…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-[13px] flex flex-col gap-[7px]">
        {visible.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none">
            <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
            <span className="text-[11px] tracking-[0.18em] uppercase">
              {chapters.length === 0 ? 'No chapters — forge a project to begin' : 'Nothing matches'}
            </span>
          </div>
        ) : (
          <>
            {visible.slice(0, limit).map(ch => (
              <QueueRow
                key={ch.id}
                chapter={ch}
                isRunning={ch.id === activeChapterId}
                activeStage={activeStage}
                ttsProg={ttsProgress[ch.id]}
                selected={ch.id === selectedId}
                isPlaying={ch.id === playingChapterId}
                playerPlaying={playerPlaying}
                onSelect={onSelect}
                onPlay={onPlay}
                onChanged={onChanged}
              />
            ))}
            {visible.length > limit && <div ref={sentinelRef} className="h-2 flex-shrink-0" />}
          </>
        )}
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Run to verify pass, commit**

Run: `cd ui; npm test; npm run typecheck` → PASS.

```powershell
git add ui/components/ChapterQueue.tsx ui/tests/ChapterQueue.test.tsx
git commit -m "feat(ui): ChapterQueue — dense rows, filters, search, live running row"
```

---

### Task 9: InspectorPanel + LiveLog embedded mode

**Files:**
- Modify: `ui/components/LiveLog.tsx`
- Create: `ui/components/InspectorPanel.tsx`
- Test: `ui/tests/InspectorPanel.test.tsx`

- [ ] **Step 1: LiveLog `embedded` prop**

In `ui/components/LiveLog.tsx`, change the component signature (`:55-57`) to:

```tsx
export default function LiveLog({ events, open, onToggle, onClear, embedded = false }: {
  events: SSEEvent[]; open: boolean; onToggle: () => void; onClear?: () => void
  /** Fill the parent instead of docking as a collapsible bottom drawer. */
  embedded?: boolean
}) {
```

Then make three adjustments inside the returned JSX:

1. Root div — class/style depend on `embedded`:

```tsx
    <div
      className={embedded
        ? 'flex flex-col h-full'
        : `flex flex-col transition-all duration-200 ${open ? 'h-52' : 'h-10'}`}
      style={embedded ? undefined : { borderTop: '1px solid #232323', background: '#000000' }}
    >
```

2. The collapse toggle button: when `embedded`, render the title block as a plain `<div>` (no `onClick`, no ▲▼ chevron). Replace the toggle `<button …onClick={onToggle}>…</button>` with:

```tsx
        {embedded ? (
          <div className="flex items-center px-5 h-10 flex-1 min-w-0 text-xs text-ink-muted">
            <div className="flex items-center gap-3 min-w-0">
              <span className="label flex-shrink-0">Live Log</span>
              {events.length > 0 && (
                <span className="text-[10px] text-ink-ghost font-mono flex-shrink-0">{events.length} events</span>
              )}
            </div>
          </div>
        ) : (
          /* …existing <button> exactly as it is today… */
        )}
```

3. The two `open &&` guards (action buttons row and log content) become `(open || embedded) &&`.

In embedded mode callers pass `open` (any value) plus a no-op `onToggle`.

- [ ] **Step 2: Write the failing InspectorPanel test**

Create `ui/tests/InspectorPanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import InspectorPanel from '@/components/InspectorPanel'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1, project_id: 1, chapter_index: 1849, title: 'The Throne of Bone',
    status: 'pending', total_chunks: 6, total_lines: 44,
    output_audio_path: null, output_file_size_bytes: null,
    processing_seconds: null, error_message: null, updated_at: '',
    ...overrides,
  }
}

const base = {
  tab: 'inspector' as const,
  onTabChange: vi.fn(),
  running: false,
  activeChapter: null,
  activeStage: null,
  liveLine: null,
  ttsProg: null,
  selectedChapter: null,
  onPlay: vi.fn(),
  onChanged: vi.fn(),
  voices: [],
  onVoicesUpdate: vi.fn(),
  forge: <div data-testid="forge-content" />,
  events: [],
  onClearLog: vi.fn(),
}

describe('InspectorPanel', () => {
  it('switches tabs', () => {
    const onTabChange = vi.fn()
    render(<InspectorPanel {...base} onTabChange={onTabChange} />)
    fireEvent.click(screen.getByRole('button', { name: /forge/i }))
    expect(onTabChange).toHaveBeenCalledWith('forge')
  })

  it('renders the live stage while synthesizing', () => {
    render(<InspectorPanel
      {...base}
      running
      activeChapter={makeChapter()}
      activeStage="synthesize"
      liveLine={{ text: 'Sunny narrowed his eyes…', speaker: 'Sunny', emotion: 'tense' }}
      ttsProg={{ done: 27, total: 44 }}
    />)
    expect(screen.getByText(/The Throne of Bone/)).toBeInTheDocument()
    expect(screen.getByText(/Sunny narrowed his eyes/)).toBeInTheDocument()
    expect(screen.getByText('Sunny')).toBeInTheDocument()
    expect(screen.getByText('tense')).toBeInTheDocument()
    expect(screen.getByText(/61%/)).toBeInTheDocument()
  })

  it('shows the full error and retry for a failed selected chapter', () => {
    render(<InspectorPanel
      {...base}
      selectedChapter={makeChapter({ status: 'error', error_message: '[failed_stage:synthesize] CUDA OOM at line 31' })}
    />)
    expect(screen.getByText(/CUDA OOM at line 31/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry chapter/i })).toBeInTheDocument()
  })

  it('renders the forge slot on the forge tab', () => {
    render(<InspectorPanel {...base} tab="forge" />)
    expect(screen.getByTestId('forge-content')).toBeInTheDocument()
  })
})
```

(61% = round(27/44·100).)

- [ ] **Step 3: Run to verify failure** — `cd ui; npm test` → cannot resolve component.

- [ ] **Step 4: Implement**

Create `ui/components/InspectorPanel.tsx`:

```tsx
'use client'
import ConfirmButton from '@/components/ConfirmButton'
import VoiceMapper from '@/components/VoiceMapper'
import LiveLog from '@/components/LiveLog'
import { deleteChapterAudio, resetChapter } from '@/lib/api'
import { formatMB, parseChapterError } from '@/lib/format'
import type { Chapter, SSEEvent, Voice } from '@/lib/types'
import type { LiveLine, Stage } from '@/hooks/usePipelineState'

export type SideTab = 'inspector' | 'voices' | 'forge' | 'log'

const TABS: { key: SideTab; label: string }[] = [
  { key: 'inspector', label: 'Inspector' },
  { key: 'voices',    label: 'Voices' },
  { key: 'forge',     label: 'Forge' },
  { key: 'log',       label: 'Log' },
]

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving the dream', synthesize: 'Synthesizing', assemble: 'Binding echoes',
}

interface Props {
  tab: SideTab
  onTabChange: (t: SideTab) => void
  running: boolean
  activeChapter: Chapter | null
  activeStage: Stage | null
  liveLine: LiveLine | null
  ttsProg: { done: number; total: number } | null
  selectedChapter: Chapter | null
  onPlay: (id: number) => void
  /** Fired after retry/redo/delete so the page refetches chapters. */
  onChanged: () => void
  voices: Voice[]
  onVoicesUpdate: () => void
  /** Page-provided Forge content (project picker + ProjectSetup). */
  forge: React.ReactNode
  events: SSEEvent[]
  onClearLog: () => void
}

function LiveStage({ chapter, stage, liveLine, ttsProg }: {
  chapter: Chapter; stage: Stage | null; liveLine: LiveLine | null
  ttsProg: { done: number; total: number } | null
}) {
  const synth = stage === 'synthesize'
  const pct = synth && ttsProg && ttsProg.total > 0
    ? Math.round((ttsProg.done / ttsProg.total) * 100) : null

  return (
    <div className="stage-glow relative px-5 pt-[22px] pb-6 border-b border-[#1a1a1a]">
      <span className="absolute top-2.5 right-3.5 text-[38px] leading-none text-[#1c1c1c] select-none" aria-hidden>✦</span>
      <div className="font-display text-[17px] tracking-[2px] leading-[1.45] text-ink-hot [text-shadow:0_0_18px_rgba(255,255,255,0.25)]">
        Ch. {chapter.chapter_index + 1}<br />{chapter.title}
      </div>
      <div className="flex items-center gap-2 my-[14px] text-[9px] tracking-[3px] uppercase text-ink-hot animate-breathe">
        <span className="equalizer" aria-hidden><span /><span /><span /></span>
        {stage ? STAGE_LABEL[stage] : 'Processing'}
        {synth && ttsProg && <> — line {ttsProg.done} of {ttsProg.total}</>}
      </div>
      {synth && liveLine ? (
        <>
          <div className="text-[15px] leading-[1.7] italic text-[#e0e0e0] min-h-[52px] pl-[15px] border-l-2 border-spell-g4">
            “{liveLine.text}”
          </div>
          <div className="text-[9px] tracking-[2.4px] uppercase text-spell-g5 mt-[11px] pl-[15px]">
            speaker <b className="text-ink-primary font-medium normal-case">{liveLine.speaker}</b>
            {' '}· emotion <b className="text-ink-primary font-medium normal-case">{liveLine.emotion}</b>
          </div>
        </>
      ) : (
        <div className="text-[11px] text-spell-g6 italic min-h-[52px] pl-[15px] border-l-2 border-spell-g3">
          {stage === 'diarize'
            ? 'The Spell reads each line, assigning voices and emotions…'
            : 'Working…'}
        </div>
      )}
      <div className={`progress-track mt-[18px] ${pct == null ? 'progress-indeterminate' : ''}`}>
        {pct != null && <i className="progress-fill" style={{ width: `${pct}%` }} />}
      </div>
      {pct != null && ttsProg && (
        <div className="font-mono text-[10px] text-spell-g6 mt-[7px] flex justify-between">
          <span>{pct}%</span>
          <span>line {ttsProg.done}∕{ttsProg.total}</span>
        </div>
      )}
    </div>
  )
}

function ChapterDetail({ chapter, onPlay, onChanged }: {
  chapter: Chapter; onPlay: (id: number) => void; onChanged: () => void
}) {
  const failed = chapter.status === 'error'
  const complete = chapter.status === 'complete'
  const err = failed ? parseChapterError(chapter.error_message) : null
  const num = String(chapter.chapter_index + 1)

  return (
    <div className="p-5 overflow-y-auto flex-1">
      <div className="font-display text-[15px] tracking-[1.5px] text-ink-primary leading-snug">
        Ch. {num} — {chapter.title}
      </div>
      <div className="text-[10px] tracking-[0.18em] uppercase text-spell-g5 mt-1">
        {chapter.status}
      </div>

      <div className="flex mt-4 pb-1.5">
        <div className="flex-1">
          <b className="font-mono text-base text-ink-primary font-medium block">{chapter.total_lines}</b>
          <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">lines</span>
        </div>
        <div className="flex-1 border-l border-spell-g2 pl-[18px]">
          <b className="font-mono text-base text-ink-primary font-medium block">{chapter.total_chunks}</b>
          <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">chunks</span>
        </div>
        <div className="flex-1 border-l border-spell-g2 pl-[18px]">
          <b className="font-mono text-base text-ink-primary font-medium block">
            {chapter.output_file_size_bytes != null ? formatMB(chapter.output_file_size_bytes) : '—'}
          </b>
          <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">audio</span>
        </div>
      </div>

      {failed && err && (
        <div className="mt-4 p-3 rounded border border-[#33141a] bg-blood-bg">
          <div className="text-[9px] tracking-[2.2px] uppercase text-blood-text mb-1.5">
            Failed at {err.stage ?? 'unknown stage'}
          </div>
          <div className="text-[11px] leading-relaxed text-[#8d4a51] break-words">{err.detail}</div>
        </div>
      )}

      <div className="flex gap-2 mt-5">
        {complete && chapter.output_audio_path != null && (
          <button className="btn flex-1" onClick={() => onPlay(chapter.id)}>▶ Play</button>
        )}
        <ConfirmButton
          className="btn flex-1"
          confirmClassName="btn flex-1"
          confirmLabel={failed ? 'Retry?' : 'Redo?'}
          onConfirm={async () => { await resetChapter(chapter.id); onChanged() }}
          ariaLabel={failed ? `Retry chapter ${num}` : `Redo chapter ${num}`}
          title="Reset and re-run this chapter"
        >↻ {failed ? 'Retry' : 'Redo'}</ConfirmButton>
        {complete && (
          <ConfirmButton
            className="btn-danger flex-1"
            confirmClassName="btn-danger flex-1"
            confirmLabel="Delete?"
            onConfirm={async () => { await deleteChapterAudio(chapter.id); onChanged() }}
            ariaLabel={`Delete audio for chapter ${num}`}
            title="Delete audio from disk"
          >✕ Delete</ConfirmButton>
        )}
      </div>
    </div>
  )
}

export default function InspectorPanel({
  tab, onTabChange, running, activeChapter, activeStage, liveLine, ttsProg,
  selectedChapter, onPlay, onChanged, voices, onVoicesUpdate, forge,
  events, onClearLog,
}: Props) {
  return (
    <aside className="deck-card flex-1 min-w-[330px] max-w-[430px] flex flex-col min-h-0 overflow-hidden">
      <div className="flex border-b border-[#1a1a1a] flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            className={`flex-1 text-center py-3 font-display text-[10px] tracking-[2.4px] uppercase border-b
                        transition-colors duration-100 ${
              tab === t.key
                ? 'text-ink-hot border-ink-hot [text-shadow:0_0_12px_rgba(255,255,255,0.4)]'
                : 'text-spell-g5 border-transparent hover:text-ink-secondary'
            }`}
            onClick={() => onTabChange(t.key)}
            aria-pressed={tab === t.key}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'inspector' && (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          {running && activeChapter && (
            <LiveStage chapter={activeChapter} stage={activeStage} liveLine={liveLine} ttsProg={ttsProg} />
          )}
          {selectedChapter ? (
            <ChapterDetail chapter={selectedChapter} onPlay={onPlay} onChanged={onChanged} />
          ) : !running ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none p-6 text-center">
              <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
              <span className="text-[11px] tracking-[0.18em] uppercase">Select a chapter to inspect</span>
            </div>
          ) : null}
        </div>
      )}

      {tab === 'voices' && (
        <div className="flex-1 overflow-y-auto p-5">
          <VoiceMapper voices={voices} onUpdate={onVoicesUpdate} />
        </div>
      )}

      {tab === 'forge' && (
        <div className="flex-1 overflow-y-auto p-5">{forge}</div>
      )}

      {tab === 'log' && (
        <LiveLog events={events} open onToggle={() => {}} onClear={onClearLog} embedded />
      )}
    </aside>
  )
}
```

- [ ] **Step 5: Run to verify pass, commit**

Run: `cd ui; npm test; npm run typecheck` → PASS (including the untouched `LiveLog.test.tsx` — drawer mode is unchanged).

```powershell
git add ui/components/InspectorPanel.tsx ui/components/LiveLog.tsx ui/tests/InspectorPanel.test.tsx
git commit -m "feat(ui): InspectorPanel — tabs, live stage, chapter detail; LiveLog embedded mode"
```

---

### Task 10: page.tsx rewrite + delete the old shell

**Files:**
- Rewrite: `ui/app/page.tsx`
- Delete: `ui/components/ChapterGrid.tsx`, `ui/components/StatsBar.tsx`, `ui/components/EmptyState.tsx`, `ui/tests/ChapterGrid.test.tsx`
- Modify: `ui/tailwind.config.ts` (prune `soul.*`, `accent`, `edge.gold`, `edge.cyan`, `twinkle`, `thread-pulse` if now unused — check with grep first)

- [ ] **Step 1: Rewrite `ui/app/page.tsx`**

```tsx
'use client'
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  getProject, getChapters, getVoices, listProjects,
  startPipeline, pausePipeline, resumePipeline, stopPipeline, getPipelineStatus,
} from '@/lib/api'
import { usePipelineState } from '@/hooks/usePipelineState'
import { formatEta } from '@/lib/format'
import CommandStrip   from '@/components/CommandStrip'
import ChapterQueue   from '@/components/ChapterQueue'
import InspectorPanel, { type SideTab } from '@/components/InspectorPanel'
import ProjectSetup   from '@/components/ProjectSetup'
import PlayerBar      from '@/components/PlayerBar'
import Toasts         from '@/components/Toasts'
import type { Project, Progress, Chapter, Voice, GenOptions } from '@/lib/types'

const STORAGE_KEY = 'pipeline_cfg'

interface SavedConfig {
  projectName: string; llmPath: string
  ttsDir: string; epubPath: string; speakers: string
  outputFormat?: string; vramCheck?: boolean
  fishDir?: string  // legacy key — migrated to ttsDir on load
}

export default function CommandDeck() {
  const [project,  setProject]  = useState<Project | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [voices,   setVoices]   = useState<Voice[]>([])
  const [projects, setProjects] = useState<(Project & { progress: Progress })[]>([])

  const [sideTab,    setSideTab]    = useState<SideTab>('forge')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const [llmPath, setLlmPath] = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf')
  const [ttsDir,  setTtsDir]  = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/index-tts/checkpoints')
  const [epubPath, setEpubPath] = useState('')
  const [speakers, setSpeakers] = useState('Sunny, Nephis, Cassie, Effie, Kai')
  const [outputFormat, setOutputFormat] = useState('mp3')
  const [vramCheck,    setVramCheck]    = useState(true)

  const [playingChId,   setPlayingChId]   = useState<number | null>(null)
  const [playerPlaying, setPlayerPlaying] = useState(false)

  const fetchChapters = useCallback(async (p: Project) => {
    try { const { chapters: chs } = await getChapters(p.id); setChapters(chs) } catch { /* silent */ }
  }, [])

  const refreshChapters = useCallback(async () => {
    if (project) return fetchChapters(project)
  }, [project, fetchChapters])

  const refreshProgress = useCallback(async () => {
    if (!project) return
    try { const { progress: p } = await getProject(project.name); setProgress(p) } catch { /* silent */ }
  }, [project])

  const refreshVoices = useCallback(async () => {
    try { const { voices: vs } = await getVoices(); setVoices(vs) } catch { /* silent */ }
  }, [])

  const onRefresh = useCallback(() => { refreshChapters(); refreshProgress() }, [refreshChapters, refreshProgress])
  const { state, dispatch } = usePipelineState(onRefresh)
  const { pipeStatus } = state

  const toast = useCallback((tone: 'warn' | 'crimson' | 'chrome', message: string) => {
    dispatch({ kind: 'toast', tone, message })
  }, [dispatch])

  const saveCfg = useCallback((patch: Partial<SavedConfig>) => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      const cfg = raw ? JSON.parse(raw) : {}
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cfg, ...patch }))
    } catch { /* quota/parse — non-fatal */ }
  }, [])

  const selectProject = useCallback(async (name: string) => {
    if (!name) return
    try {
      const { project: p, progress: pr } = await getProject(name)
      setProject(p); setProgress(pr); setSideTab('voices'); setSelectedId(null); fetchChapters(p)
      getPipelineStatus().then(s => dispatch({ kind: 'set-status', status: s.status })).catch(() => {})
      saveCfg({ projectName: name })
    } catch { /* */ }
  }, [fetchChapters, saveCfg, dispatch])

  useEffect(() => {
    refreshVoices()
    listProjects().then(({ projects: ps }) => setProjects(ps)).catch(() => {})
    // Always sync with the backend — the pipeline may still be running from a
    // previous browser session.
    getPipelineStatus().then(s => dispatch({ kind: 'set-status', status: s.status })).catch(() => {})
    let cfg: Partial<SavedConfig> = {}
    try { const r = localStorage.getItem(STORAGE_KEY); if (r) cfg = JSON.parse(r) } catch { /* */ }
    if (cfg.llmPath && !cfg.llmPath.includes('7b')) setLlmPath(cfg.llmPath)
    // Migrate legacy fishDir, but ignore stale Fish Speech paths — TTS is now
    // IndexTTS2 (index-tts/checkpoints). A saved fish-speech dir would fail.
    const savedTtsDir = cfg.ttsDir || cfg.fishDir
    if (savedTtsDir && !/fish[-_ ]?speech/i.test(savedTtsDir)) setTtsDir(savedTtsDir)
    if (cfg.epubPath) setEpubPath(cfg.epubPath)
    if (cfg.speakers) setSpeakers(cfg.speakers)
    if (cfg.outputFormat) setOutputFormat(cfg.outputFormat)
    if (cfg.vramCheck != null) setVramCheck(cfg.vramCheck)
    if (cfg.projectName) {
      getProject(cfg.projectName)
        .then(({ project: p, progress: pr }) => {
          setProject(p); setProgress(pr); setSideTab('voices'); fetchChapters(p)
        })
        .catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll while running — catches missed SSE terminal events (e.g. sleep).
  useEffect(() => {
    if (pipeStatus !== 'running') return
    const id = setInterval(() => {
      refreshChapters(); refreshProgress()
      getPipelineStatus().then(s => {
        if (s.status !== 'running') dispatch({ kind: 'set-status', status: s.status })
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(id)
  }, [pipeStatus, refreshChapters, refreshProgress, dispatch])

  function buildStartParams() {
    const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)
    return {
      llm_model_path: llmPath, tts_model_dir: ttsDir,
      speakers: speakerList, output_format: outputFormat,
      vram_check_enabled: vramCheck,
    }
  }

  async function handleStart() {
    if (!project) return
    try {
      await startPipeline({ project_name: project.name, ...buildStartParams() })
      dispatch({ kind: 'set-status', status: 'running' })
      setSideTab('inspector')
    } catch (err) {
      toast('crimson', err instanceof Error ? err.message : 'Failed to start')
    }
  }

  async function handlePause()  { try { await pausePipeline();  dispatch({ kind: 'set-status', status: 'paused'  }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to pause')  } }
  async function handleResume() { try { await resumePipeline(); dispatch({ kind: 'set-status', status: 'running' }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to resume') } }
  async function handleStop()   { try { await stopPipeline();   dispatch({ kind: 'set-status', status: 'stopped' }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to stop')   } }

  function handleProjectCreated(
    p: Project, prog: Progress, llm: string, tts: string, spkList: string[], opts: GenOptions,
  ) {
    setProject(p); setProgress(prog); setLlmPath(llm); setTtsDir(tts)
    setSpeakers(spkList.join(', ')); setOutputFormat(opts.outputFormat)
    setVramCheck(opts.vramCheck); setSideTab('voices')
    saveCfg({
      projectName: p.name, llmPath: llm, ttsDir: tts, epubPath,
      speakers: spkList.join(', '),
      outputFormat: opts.outputFormat, vramCheck: opts.vramCheck,
    })
    fetchChapters(p)
    startPipeline({
      project_name: p.name, llm_model_path: llm, tts_model_dir: tts, speakers: spkList,
      chapter_range: opts.chapterRange, output_format: opts.outputFormat,
      vram_check_enabled: opts.vramCheck,
    })
      .then(() => { dispatch({ kind: 'set-status', status: 'running' }); setSideTab('inspector') })
      .catch(err => {
        const msg = err instanceof Error ? err.message : 'Failed to start'
        if (msg.toLowerCase().includes('already running')) dispatch({ kind: 'set-status', status: 'running' })
        else toast('crimson', msg)
      })
  }

  // ETA from measured per-chapter processing time × chapters left.
  const eta = useMemo(() => {
    if (!progress || pipeStatus !== 'running') return ''
    const timed = chapters.filter(c => c.processing_seconds != null && c.status === 'complete')
    if (!timed.length) return ''
    const avg = timed.reduce((s, c) => s + (c.processing_seconds ?? 0), 0) / timed.length
    const remaining = progress.total - progress.complete - progress.error
    return formatEta(avg * remaining)
  }, [chapters, progress, pipeStatus])

  // Listenable chapters, in book order — the global player's queue.
  const playerQueue = useMemo(
    () => chapters
      .filter(c => c.status === 'complete' && c.output_audio_path != null)
      .sort((a, b) => a.chapter_index - b.chapter_index),
    [chapters],
  )

  const activeChapter   = useMemo(() => chapters.find(c => c.id === state.activeChId) ?? null, [chapters, state.activeChId])
  const selectedChapter = useMemo(() => chapters.find(c => c.id === selectedId) ?? null, [chapters, selectedId])
  const ttsProg = state.activeChId != null ? state.ttsProgress[state.activeChId] ?? null : null

  const canStart = Boolean(project && llmPath && ttsDir
    && ['idle', 'stopped', 'complete', 'error'].includes(pipeStatus))

  const forge = (
    <div className="space-y-5">
      {projects.length > 0 && (
        <div>
          <label className="label block mb-1.5">Open existing project</label>
          <select
            value={project?.name ?? ''}
            onChange={(e) => selectProject(e.target.value)}
            className="w-full px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.name}>
                {p.name} — {p.progress.complete}/{p.progress.total} done
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[11px] text-ink-ghost">Or forge a new one from an EPUB below.</p>
        </div>
      )}
      <ProjectSetup
        initialEpub={epubPath} initialLlm={llmPath}
        initialTtsDir={ttsDir} initialSpeakers={speakers}
        onCreated={handleProjectCreated}
      />
    </div>
  )

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Toasts toasts={state.toasts} onDismiss={(id) => dispatch({ kind: 'dismiss-toast', id })} />

      <CommandStrip
        pipeStatus={pipeStatus}
        connected={state.connected}
        progress={progress}
        activeStage={state.activeStage}
        eta={eta}
        vramMb={state.vramMb}
        canStart={canStart}
        onStart={handleStart}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
      />

      <main className="flex flex-1 min-h-0 gap-[18px] px-6 py-[18px]">
        <ChapterQueue
          chapters={chapters}
          activeChapterId={state.activeChId}
          activeStage={state.activeStage}
          ttsProgress={state.ttsProgress}
          selectedId={selectedId}
          onSelect={(id) => { setSelectedId(id); setSideTab('inspector') }}
          playingChapterId={playingChId}
          playerPlaying={playerPlaying}
          onPlay={setPlayingChId}
          onChanged={onRefresh}
        />
        <InspectorPanel
          tab={sideTab}
          onTabChange={setSideTab}
          running={pipeStatus === 'running' || pipeStatus === 'paused'}
          activeChapter={activeChapter}
          activeStage={state.activeStage}
          liveLine={state.liveLine}
          ttsProg={ttsProg}
          selectedChapter={selectedChapter}
          onPlay={setPlayingChId}
          onChanged={onRefresh}
          voices={voices}
          onVoicesUpdate={refreshVoices}
          forge={forge}
          events={state.events}
          onClearLog={() => dispatch({ kind: 'clear-log' })}
        />
      </main>

      <PlayerBar
        queue={playerQueue}
        currentId={playingChId}
        onCurrentChange={setPlayingChId}
        onPlayingChange={setPlayerPlaying}
      />
    </div>
  )
}
```

- [ ] **Step 2: Delete the old shell**

```powershell
git rm ui/components/ChapterGrid.tsx ui/components/StatsBar.tsx ui/components/EmptyState.tsx ui/tests/ChapterGrid.test.tsx
```

- [ ] **Step 3: Prune dead tokens**

Grep before removing — only prune what is now truly unreferenced:

```powershell
cd ui
findstr /s /i "soul\." app\*.tsx components\*.tsx hooks\*.ts
findstr /s /i "twinkle thread-pulse weaver-thread accent" app\*.tsx components\*.tsx app\globals.css
```

VoiceMapper is known to use `weaver-thread`/`animate-thread-pulse` and possibly `animate-twinkle` — keep whatever still matches. Remove from `tailwind.config.ts` only entries with zero hits (expected removable: `soul`, `accent`, `edge.gold`, `edge.cyan`).

- [ ] **Step 4: Full gates**

Run: `cd ui; npm test; npm run typecheck; npm run build`
Expected: all green. Then the python suites (unchanged but cheap insurance):
`python tests/test_orchestrator.py; python tests/test_tts_engine.py; python tests/test_api.py; python tests/test_llm_director.py; python tests/test_epub_parser.py; python tests/test_state_manager.py; python tests/test_audio_assembler.py`

- [ ] **Step 5: Commit**

```powershell
git add -A ui
git commit -m "feat(ui): Command Deck shell — page rewrite, old grid/stats/empty-state removed"
```

---

### Task 11: Live verification (manual gate)

**Files:** none (verification only)

- [ ] **Step 1: Start both services**

Run: `.\start.ps1` (or backend `python -m uvicorn api:app --port 8000 --reload` from `src/`, frontend `npm run dev` from `ui/`). Open http://localhost:3000.

- [ ] **Step 2: Static checklist (no pipeline run needed)**

- Header: flickering NIGHTMARE SPELL wordmark, ✦ status mark, RUN button bone-white.
- Queue: rows render with ✦ marks, filters + search work, failed rows (if any) are crimson with "Failed at <stage>".
- Inspector: tabs switch; Voices shows the voice map; Forge shows project picker + setup; Log shows past events.
- Player: pick a complete chapter's ▶ — bottom player appears, ✦ seek thumb, keyboard transport works.
- Ghost ✦ watermark bottom-right; vignette at the edges; toasts top-right above the vignette.

- [ ] **Step 3: Live pipeline run (the spec's manual gate)**

Reset or pick one short chapter and Run. Verify:
- Running row enlarges, glow-pulses, equalizer animates; progress bar fills with shimmer during synthesis (≈17 s/line — be patient).
- Inspector live stage shows the current line text + speaker + emotion, updating every line (this proves the Task 1–2 backend rider end-to-end).
- Diarize stage shows the indeterminate scan, not a fake bar.
- On completion: chrome "Congratulations, Sleeper" toast; chapter flips to Complete; player can play it.
- Kill the backend mid-run briefly: header shows LINK SEVERED, then recovers after restart (reconnect + snapshot refetch).

- [ ] **Step 4: Update CLAUDE.md UI notes if behavior descriptions drifted, commit any fixes**

```powershell
git add -A
git commit -m "fix(ui): post-live-run polish for Command Deck"
```

(Skip the commit if nothing needed fixing.)

---

## Self-review (done at plan time)

- **Spec coverage:** §2 visual system → Task 4; §3 layout → Tasks 7–10; §4 approach → file structure + Tasks 7–10; §5.1 → unchanged; §5.2 rider → Tasks 1–3; §5.3 hook → Task 6; §5.4 diarize indeterminate → Tasks 8–9 (`progress-indeterminate`); §6 error handling → Tasks 4 (toast tones), 8 (failed rows), 9 (detail + retry/reset), 7 (LINK SEVERED), 10 (control-failure toasts); §7 testing → every task carries its tests; live gate = Task 11. Speaker histogram consciously cut (header note).
- **Type consistency:** `Stage`/`PipeStatus`/`LiveLine` defined once in `usePipelineState.ts` and imported everywhere; `ToastTone = warn|crimson|chrome` matches CSS classes; callback contract `(done, total, line)` consistent across Tasks 1, 2, and the fake.
- **Placeholders:** none — every step has full code or an exact command.
