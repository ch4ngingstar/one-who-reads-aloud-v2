# Plan 008: Add POST /api/chapters/reset-range for batch chapter reset

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

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

`POST /api/chapters/{chapter_id}/reset` resets one chapter at a time. After a
long pipeline run that errored on many chapters, recovering requires N separate
API calls (or running `scripts/fix_errored.py` manually). A batch endpoint
that accepts a project ID, an optional chapter-index range, and an optional
status filter can reset all matching chapters in one request.

The existing `reset_chapter_to_pending()` in `StateManager` already handles the
file deletion + DB reset for one chapter. This plan calls it in a loop.

## Current state

- `src/api.py:409-434` — per-chapter reset endpoint (pattern for new endpoint):

```python
# src/api.py:409-434
@app.post("/api/chapters/{chapter_id}/reset")
async def reset_chapter(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """Reset a chapter to pending so the pipeline will re-process it."""
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chapter not found.")

    ok = sm.reset_chapter_to_pending(chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chapter not found.")

    if row["output_audio_path"]:
        p = _resolve_data_path(row["output_audio_path"])
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    return {"reset": chapter_id}
```

Note: `reset_chapter_to_pending` already handles audio file deletion internally
(it deletes per-line WAVs). The endpoint above additionally deletes the chapter
MP3. The batch endpoint must do the same for each chapter.

- `src/state_manager.py:313-337` — `reset_chapter_to_pending` (already handles
  line WAV deletion in the DB-commit path; chapter MP3 deletion is done by the
  API layer above it):

```python
# src/state_manager.py:313-337 (abridged)
def reset_chapter_to_pending(self, chapter_id: int) -> bool:
    ...
    return n > 0
```

- Valid chapter statuses: `pending`, `diarized`, `tts_done`, `assembled`,
  `complete`, `error` (defined in `CHAPTER_STATUSES` in `state_manager.py:46`).

## Commands you will need

| Purpose      | Command                    | Expected on success  |
|--------------|----------------------------|----------------------|
| API tests    | `python tests/test_api.py` | all PASS, exit 0     |
| UI typecheck | `cd ui && npm run typecheck` | exit 0, no errors  |

## Scope

**In scope**:
- `src/api.py` — one new POST endpoint + one new Pydantic request model
- `ui/lib/api.ts` — one new `resetChapters` client helper

**Out of scope**:
- `StateManager` — no changes needed
- Any UI component — calling this endpoint from the UI is a follow-up
- `scripts/fix_errored.py` — leave it; it remains a useful manual tool

## Git workflow

- Branch: `advisor/008-batch-chapter-reset`
- One commit: `feat(api): add POST /api/chapters/reset-range for batch reset`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add request model to `src/api.py`

In the `# ── Pydantic request/response models ──` section (after the existing
`VoiceSet` model, around line 82), add:

```python
class ChapterResetRange(BaseModel):
    project_id: int
    status_filter: Optional[list[str]] = None   # e.g. ["error", "tts_done"]; None = all
    chapter_range: Optional[list[int]] = None   # [start_index, end_index] inclusive; None = all
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from api import ChapterResetRange; print('ok')"` → `ok`.

### Step 2: Add the endpoint to `src/api.py`

Insert after the existing `reset_chapter` handler (after line 434), still in
the `# ── Chapters ──` section:

```python
@app.post("/api/chapters/reset-range", status_code=200)
async def reset_chapters_range(
    req: ChapterResetRange,
    sm: StateManager = Depends(get_sm),
):
    """Reset multiple chapters to pending.

    Filters by project_id, optional status_filter list, and optional
    chapter_range [start_index, end_index] inclusive. Returns the list of
    reset chapter IDs. Chapters already at 'pending' are skipped.
    """
    if req.status_filter:
        from state_manager import CHAPTER_STATUSES
        invalid = set(req.status_filter) - CHAPTER_STATUSES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status values: {sorted(invalid)}. "
                       f"Valid: {sorted(CHAPTER_STATUSES)}"
            )

    if req.chapter_range:
        if len(req.chapter_range) != 2:
            raise HTTPException(status_code=400,
                                detail="chapter_range must have exactly 2 elements: [start, end]")
        if req.chapter_range[0] > req.chapter_range[1]:
            raise HTTPException(status_code=400,
                                detail="chapter_range[0] must be <= chapter_range[1]")

    all_chapters = sm.get_all_chapters(req.project_id)
    if not all_chapters:
        raise HTTPException(status_code=404,
                            detail=f"No chapters found for project_id={req.project_id}")

    # Apply filters
    candidates = all_chapters
    if req.status_filter:
        candidates = [c for c in candidates if c["status"] in req.status_filter]
    if req.chapter_range:
        s, e = req.chapter_range
        candidates = [c for c in candidates if s <= c["chapter_index"] <= e]

    # Skip chapters already pending
    to_reset = [c for c in candidates if c["status"] != "pending"]

    reset_ids: list[int] = []
    for ch in to_reset:
        ok = sm.reset_chapter_to_pending(ch["id"])
        if ok:
            # Also delete the assembled MP3 if present (mirrors single-chapter reset)
            if ch.get("output_audio_path"):
                p = _resolve_data_path(ch["output_audio_path"])
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            reset_ids.append(ch["id"])

    return {"reset": reset_ids, "count": len(reset_ids)}
```

**Verify**: Smoke test with a test client (no models needed):
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
pid = sm.seed_project({'source_epub':'b.epub','total_chapters':1,
  'chapters':[{'chapter_index':0,'title':'Ch','chunks':[{'chunk_index':0,'text':'x','word_count':1}]}]})
app.dependency_overrides[get_sm] = lambda: sm
c = TestClient(app)
r = c.post('/api/chapters/reset-range', json={'project_id': pid, 'status_filter': ['error']})
print(r.status_code, r.json())
"
```
→ `200 {'reset': [], 'count': 0}` (no error chapters to reset).

### Step 3: Add `resetChapters` to `ui/lib/api.ts`

Append to `ui/lib/api.ts`, after the existing `resetChapter` function:

```typescript
export async function resetChapters(params: {
  project_id: number
  status_filter?: string[] | null
  chapter_range?: [number, number] | null
}): Promise<{ reset: number[]; count: number }> {
  return req('/chapters/reset-range', { method: 'POST', body: JSON.stringify(params) })
}
```

**Verify**: `cd ui && npm run typecheck` → exit 0.

### Step 4: Run all tests

**Verify**: `python tests/test_api.py` → all PASS, exit 0.
**Verify**: `cd ui && npm run typecheck` → exit 0.

## Test plan

Add to `tests/test_api.py`, modelled after `test_pipeline_start_project_not_found`:

```python
def test_reset_range_no_chapters():
    """404 when project has no chapters."""
    client, _, _ = _make_client()
    r = client.post("/api/chapters/reset-range",
                    json={"project_id": 9999})
    assert r.status_code == 404
    print("  PASS test_reset_range_no_chapters")


def test_reset_range_all_error():
    """Resets all 'error' chapters; pending stays pending."""
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=3)
    chs = sm.get_all_chapters(pid)
    # Mark first two as error
    sm.mark_chapter_status(chs[0]["id"], "error", error_message="boom")
    sm.mark_chapter_status(chs[1]["id"], "error", error_message="boom")
    # Third stays pending
    client, _, _ = _make_client(sm=sm)

    r = client.post("/api/chapters/reset-range",
                    json={"project_id": pid, "status_filter": ["error"]})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert set(data["reset"]) == {chs[0]["id"], chs[1]["id"]}

    # Verify DB reset
    for ch in sm.get_all_chapters(pid):
        assert ch["status"] == "pending", f"ch {ch['id']} should be pending"
    print("  PASS test_reset_range_all_error")


def test_reset_range_chapter_range_filter():
    """chapter_range limits which chapters are reset."""
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=5)
    chs = sm.get_all_chapters(pid)
    for ch in chs:
        sm.mark_chapter_status(ch["id"], "complete")
    client, _, _ = _make_client(sm=sm)

    r = client.post("/api/chapters/reset-range",
                    json={"project_id": pid, "chapter_range": [1, 2]})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    # chapters at index 0, 3, 4 untouched
    statuses = {c["chapter_index"]: c["status"]
                for c in sm.get_all_chapters(pid)}
    assert statuses[0] == "complete"
    assert statuses[1] == "pending"
    assert statuses[2] == "pending"
    assert statuses[3] == "complete"
    print("  PASS test_reset_range_chapter_range_filter")
```

Add all three to the `TESTS` list and run.

**Verify**: `python tests/test_api.py` → all PASS including three new tests.

## Done criteria

- [ ] `POST /api/chapters/reset-range` endpoint exists in `src/api.py`
- [ ] `ChapterResetRange` Pydantic model exists in `src/api.py`
- [ ] `resetChapters` function exists in `ui/lib/api.ts`
- [ ] `python tests/test_api.py` exits 0 including three new tests
- [ ] `cd ui && npm run typecheck` exits 0
- [ ] Only `src/api.py` and `ui/lib/api.ts` modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- The `CHAPTER_STATUSES` import path changes — it is at
  `state_manager.py:46`; verify before using it in the endpoint.
- A routing conflict: FastAPI matches `/api/chapters/reset-range` before
  `/api/chapters/{chapter_id}/...` because `reset-range` could be parsed as a
  chapter_id. To prevent this, ensure the new endpoint is **defined before**
  any `{chapter_id}` routes in `src/api.py`. If the existing per-chapter
  endpoints come first, move the new endpoint above them.

## Maintenance notes

The batch reset is synchronous: it processes chapters one at a time in a loop.
For a project with thousands of error chapters, this could take a few seconds
due to the file deletion per chapter. If the timeout becomes a concern, consider
running it in a background task (`asyncio.to_thread`). For now, the response
time is bounded by the number of errored chapters × one file stat + unlink, which
is sub-second for typical failure counts.

If voice line WAV directories (`data/audio/ch_XXXX/`) grow large, the WAV file
deletion inside `reset_chapter_to_pending` (already implemented in
`StateManager`) handles it per chapter — no changes needed here.
