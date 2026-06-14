# Plan 001: Replace hardcoded machine-specific paths with empty defaults in UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 3831319..HEAD -- ui/app/page.tsx`
> If this file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

`ui/app/page.tsx` hard-codes two absolute paths from the developer's Windows
machine as React `useState` default values. Any other user who opens the app
for the first time sees their form pre-filled with paths that do not exist on
their system, making the "Forge" panel appear broken before they can even
start. Removing the defaults and replacing them with empty strings makes the
first-run experience correct — the user fills in their own paths, which are
then persisted to `localStorage` for subsequent sessions.

## Current state

- `ui/app/page.tsx` — The root page component. Lines 36–37 initialise two
  state variables with absolute paths anchored to `/Users/alityan/`:

```tsx
// ui/app/page.tsx:36-37
const [llmPath, setLlmPath] = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/models/Qwen3-14B-Q4_K_M.gguf')
const [ttsDir,  setTtsDir]  = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/index-tts/checkpoints')
```

- Lines 107–112 load saved config from `localStorage` on mount. The `llmPath`
  load has a guard that filters out old 7B model paths:

```tsx
// ui/app/page.tsx:108
if (cfg.llmPath && !cfg.llmPath.includes('7b')) setLlmPath(cfg.llmPath)
```

  With empty defaults, there is no need to reject a saved 7B path — if the
  user deliberately saved one, they want it. Remove the `'7b'` filter and
  load any saved value.

- The repo follows conventional commits (`fix:`, `refactor:`, `feat:`, `docs:`).
  Branch naming convention observed: `advisor/NNN-slug`.

## Commands you will need

| Purpose     | Command                         | Expected on success        |
|-------------|----------------------------------|----------------------------|
| Typecheck   | `cd ui && npm run typecheck`     | exit 0, no errors          |
| UI tests    | `cd ui && npm test`              | exit 0, all pass           |

## Scope

**In scope** (the only file you should modify):
- `ui/app/page.tsx`

**Out of scope** (do NOT touch):
- Any other component or hook — the `llmPath` and `ttsDir` states are only
  initialised here; downstream components receive them as props and need no
  change.
- `localStorage` key names or `SavedConfig` interface — structure is unchanged.

## Git workflow

- Branch: `advisor/001-hardcoded-paths`
- One commit; message style: `fix(ui): remove hardcoded machine paths from default state`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Replace the two hardcoded `useState` defaults with empty strings

In `ui/app/page.tsx`, change lines 36–37 from:

```tsx
const [llmPath, setLlmPath] = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/models/Qwen3-14B-Q4_K_M.gguf')
const [ttsDir,  setTtsDir]  = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/index-tts/checkpoints')
```

to:

```tsx
const [llmPath, setLlmPath] = useState('')
const [ttsDir,  setTtsDir]  = useState('')
```

**Verify**: `grep -n "alityan" ui/app/page.tsx` → no matches.

### Step 2: Remove the `'7b'` filter from the localStorage load

In `ui/app/page.tsx`, change line 108 from:

```tsx
if (cfg.llmPath && !cfg.llmPath.includes('7b')) setLlmPath(cfg.llmPath)
```

to:

```tsx
if (cfg.llmPath) setLlmPath(cfg.llmPath)
```

**Verify**: `grep -n "includes.*7b" ui/app/page.tsx` → no matches.

### Step 3: Typecheck and test

**Verify**: `cd ui && npm run typecheck` → exit 0, zero errors.
**Verify**: `cd ui && npm test` → exit 0, all existing tests pass.

## Test plan

No new tests are needed — this is a value change to two string literals and a
removal of a dead filter. The existing test suite confirms no regressions.

If you want to confirm the behaviour manually: clear `localStorage` in browser
devtools, reload the UI, and confirm the LLM path and TTS dir fields are empty.

## Done criteria

- [ ] `grep -rn "alityan" ui/app/page.tsx` returns no matches
- [ ] `grep -n "includes.*7b" ui/app/page.tsx` returns no matches
- [ ] `cd ui && npm run typecheck` exits 0
- [ ] `cd ui && npm test` exits 0
- [ ] Only `ui/app/page.tsx` is modified (`git diff --name-only`)
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

- The code at lines 36–37 does not match the excerpts above (file has drifted).
- TypeScript errors appear after the change.

## Maintenance notes

If placeholder text (e.g. "C:/models/...") is added to the path input fields
later, update the `placeholder` prop on those inputs in `ProjectSetup.tsx` —
do not reinstate hardcoded defaults in `useState`.
