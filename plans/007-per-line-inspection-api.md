# Plan 007: Add GET /api/chapters/{id}/lines endpoint for diarization inspection

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- src/api.py ui/lib/api.ts ui/lib/types.ts`
> On any mismatch with the excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

The pipeline writes per-line speaker/emotion data to the `lines` table after
diarization, but there is no API to read it. Debugging a misattribution
(wrong speaker on a line) currently requires either a SQLite browser or running
`scripts/dbcheck.py` manually. Adding a read endpoint surfaces this data in the
UI and future tooling without touching any pipeline logic.

The `StateManager.get_lines_for_chapter()` method already returns everything
needed — this plan wires it to an HTTP endpoint, adds the TypeScript type, and
adds a client helper.

## Current state

- `src/state_manager.py:394-403` — the method that returns all line data:

```python
# src/state_manager.py:394-403
def get_lines_for_chapter(self, chapter_id: int) -> list:
    """All lines for a chapter. Read by Module 5 (Audio Assembler)."""
    with self._conn() as conn:
        rows = conn.execute(
            """SELECT id, line_index, speaker, text, emotion, status, audio_path, error_message
               FROM lines WHERE chapter_id = ?
               ORDER BY line_index""",
            (chapter_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- `src/api.py:376-386` — nearest existing chapter endpoint (list chapters),
  used as a pattern for the new endpoint:

```python
# src/api.py:376-386
@app.get("/api/chapters/{project_id}")
async def list_chapters(
    project_id: int,
    sm: StateManager = Depends(get_sm),
):
    chapters = sm.get_all_chapters(project_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found.")
    return {"chapters": chapters, "total": len(chapters)}
```

- `ui/lib/types.ts` — type definitions; `Chapter` is at lines 24–37. The new
  `Line` type goes here.

- `ui/lib/api.ts` — client helpers; all existing helpers follow the same
  `req()` wrapper pattern.

## Commands you will need

| Purpose      | Command                    | Expected on success  |
|--------------|----------------------------|----------------------|
| API tests    | `python tests/test_api.py` | all PASS, exit 0     |
| UI typecheck | `cd ui && npm run typecheck` | exit 0, no errors  |

## Scope

**In scope**:
- `src/api.py` — one new GET endpoint
- `ui/lib/types.ts` — one new `Line` interface
- `ui/lib/api.ts` — one new `getLines` helper function

**Out of scope**:
- Any UI component (InspectorPanel, ChapterQueue, etc.) — displaying the data
  is a follow-up; this plan only exposes it.
- `StateManager.get_lines_for_chapter` — already correct, do not touch.

## Git workflow

- Branch: `advisor/007-per-line-inspection-api`
- One commit: `feat(api): add GET /api/chapters/{id}/lines for diarization inspection`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add the API endpoint to `src/api.py`

Insert the new endpoint in `src/api.py` immediately after the existing
`list_chapters` handler (after line 386, before the `delete_chapter_audio`
handler). Add it in the `# ── Chapters ──` section:

```python
@app.get("/api/chapters/{chapter_id}/lines")
async def list_chapter_lines(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """All diarized lines for a chapter (speaker, text, emotion, status, audio_path)."""
    lines = sm.get_lines_for_chapter(chapter_id)
    return {"lines": lines, "total": len(lines)}
```

**Verify**: Start a test client and hit the new endpoint:
```bash
python -c "
import sys; sys.path.insert(0,'src')
from fastapi.testclient import TestClient
from api import app, get_sm
from state_manager import StateManager
import tempfile

tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tmp.close()
sm = StateManager(tmp.name)
app.dependency_overrides[get_sm] = lambda: sm
c = TestClient(app)
r = c.get('/api/chapters/1/lines')
print(r.status_code, r.json())
"
```
→ `200 {'lines': [], 'total': 0}` (chapter 1 has no lines — that's expected).

### Step 2: Add `Line` interface to `ui/lib/types.ts`

Append after the `Voice` interface (after line 53 of the current file):

```typescript
export interface Line {
  id: number
  line_index: number
  speaker: string
  text: string
  emotion: string
  status: 'pending' | 'tts_done' | 'failed'
  audio_path: string | null
  error_message: string | null
}
```

**Verify**: `grep -n "interface Line" ui/lib/types.ts` → one match.

### Step 3: Add `getLines` client helper to `ui/lib/api.ts`

Append to `ui/lib/api.ts` in the `# ── Chapters ──` section (after the
`getChapters` function):

```typescript
export async function getLines(
  chapterId: number,
): Promise<{ lines: Line[]; total: number }> {
  return req(`/chapters/${chapterId}/lines`)
}
```

Also add `Line` to the import at the top of `ui/lib/api.ts`:

```typescript
// BEFORE
import type { Chapter, Progress, Project, PipelineStatusResponse, Voice } from './types'

// AFTER
import type { Chapter, Line, Progress, Project, PipelineStatusResponse, Voice } from './types'
```

**Verify**: `cd ui && npm run typecheck` → exit 0, no errors.

### Step 4: Run all tests

**Verify**: `python tests/test_api.py` → all PASS, exit 0.
**Verify**: `cd ui && npm run typecheck` → exit 0.

## Test plan

Add two tests to `tests/test_api.py`, modelled after the existing
`test_list_chapters` pattern:

```python
def test_list_lines_empty():
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=1)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    client, _, _ = _make_client(sm=sm)

    r = client.get(f"/api/chapters/{ch_id}/lines")
    assert r.status_code == 200
    data = r.json()
    assert data["lines"] == []
    assert data["total"] == 0
    print("  PASS test_list_lines_empty")


def test_list_lines_after_diarize():
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=1)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "Hello.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny",    "text": "Cold.", "emotion": "cold"},
    ])
    client, _, _ = _make_client(sm=sm)

    r = client.get(f"/api/chapters/{ch_id}/lines")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["lines"][0]["speaker"] == "Narrator"
    assert data["lines"][1]["emotion"] == "cold"
    print("  PASS test_list_lines_after_diarize")
```

Add both to the `TESTS` list and run.

**Verify**: `python tests/test_api.py` → all PASS including two new tests.

## Done criteria

- [ ] `GET /api/chapters/{chapter_id}/lines` returns `{"lines": [...], "total": N}`
- [ ] `Line` interface exists in `ui/lib/types.ts`
- [ ] `getLines` function exists in `ui/lib/api.ts` and `Line` is imported there
- [ ] `python tests/test_api.py` exits 0 including two new tests
- [ ] `cd ui && npm run typecheck` exits 0
- [ ] Only `src/api.py`, `ui/lib/types.ts`, `ui/lib/api.ts` modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- `get_lines_for_chapter` signature differs from the excerpt — verify the
  method in `state_manager.py` before writing the endpoint.
- TypeScript errors appear after adding the `Line` import — check that
  `ui/lib/types.ts` exports `Line` with `export interface`.

## Maintenance notes

The endpoint is read-only and calls a method already used by the audio
assembler — no write path risk. If the `lines` table schema changes (new
columns), `get_lines_for_chapter` selects specific columns, so the endpoint
response shape is stable as long as the DB method's SELECT list is not changed.

To display lines in the UI's InspectorPanel, call `getLines(chapter.id)` after
selecting a chapter in the Inspector's detail tab. That is a follow-up UI task.
