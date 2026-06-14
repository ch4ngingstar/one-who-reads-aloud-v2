# Plan 002: Consolidate list_projects progress into a single DB connection

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- src/state_manager.py src/api.py`
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

`GET /api/projects` calls `sm.list_projects()` to fetch all projects, then
loops over them calling `sm.get_progress(p["id"])` for each one. Every
`get_progress()` call opens a new SQLite connection, queries, and closes.
For N projects that is N+1 connections for what should be 2 queries on 1
connection. The fix adds a single-connection method to `StateManager` that
fetches projects and aggregates chapter counts in one trip.

In practice this project usually has only one or two EPUB projects, so the
performance delta is small — but the pattern is inconsistent with the rest of
the codebase and opens N connections on a hot endpoint.

## Current state

- `src/state_manager.py` — `StateManager` class; each method opens its own
  connection via the `_conn()` context manager and closes it on exit.

```python
# src/state_manager.py:249-255
def list_projects(self) -> list:
    """All projects (newest first) for the UI project picker."""
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
```

```python
# src/state_manager.py:461-497
def get_progress(self, project_id: int) -> dict:
    with self._conn() as conn:
        rows = conn.execute(
            """SELECT status, COUNT(*) AS cnt
               FROM chapters WHERE project_id = ?
               GROUP BY status""",
            (project_id,),
        ).fetchall()
    counts = {r["status"]: r["cnt"] for r in rows}
    total = sum(counts.values())
    complete = counts.get("complete", 0)
    return {
        "total":     total,
        "pending":   counts.get("pending", 0),
        "diarized":  counts.get("diarized", 0),
        "tts_done":  counts.get("tts_done", 0),
        "assembled": counts.get("assembled", 0),
        "complete":  complete,
        "error":     counts.get("error", 0),
        "pct_complete": round(complete / total * 100, 1) if total else 0.0,
    }
```

- `src/api.py:275-281` — the endpoint that causes the N+1:

```python
# src/api.py:275-281
@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)):
    """All projects with per-project progress, for the UI project picker."""
    projects = sm.list_projects()
    for p in projects:
        p["progress"] = sm.get_progress(p["id"])
    return {"projects": projects}
```

- The progress dict shape is consumed by the UI (`ui/lib/types.ts`: `Progress`
  interface). Do not change the shape of the returned dict.

- Error handling pattern: `_conn()` rolls back on exception and re-raises;
  no try/except in the caller — match this pattern.

## Commands you will need

| Purpose         | Command                                     | Expected on success   |
|-----------------|---------------------------------------------|-----------------------|
| Run API tests   | `python tests/test_api.py`                  | all PASS, exit 0      |
| Run state tests | `python tests/test_state_manager.py`        | all PASS, exit 0      |

## Scope

**In scope**:
- `src/state_manager.py` — add one new method `list_projects_with_progress()`
- `src/api.py` — update `list_projects` endpoint to call the new method

**Out of scope**:
- `get_progress()` — leave it unchanged; it is called individually elsewhere
  (e.g. `get_project` endpoint at `api.py:288`).
- Response shape — must remain identical.
- Any UI file.

## Git workflow

- Branch: `advisor/002-list-projects-nplus1`
- One commit; message: `perf(state): consolidate list_projects progress into single connection`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `list_projects_with_progress()` to `StateManager`

Insert the new method after `list_projects()` in `src/state_manager.py`
(after line 255, before `get_all_chapters`):

```python
def list_projects_with_progress(self) -> list:
    """All projects with progress dicts (newest first). One connection, two queries."""
    with self._conn() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()]

        # Aggregate chapter counts for all projects in a single query.
        rows = conn.execute(
            "SELECT project_id, status, COUNT(*) AS cnt "
            "FROM chapters GROUP BY project_id, status"
        ).fetchall()

    chapter_counts: dict = {}
    for row in rows:
        pid = row["project_id"]
        if pid not in chapter_counts:
            chapter_counts[pid] = {}
        chapter_counts[pid][row["status"]] = row["cnt"]

    for p in projects:
        counts = chapter_counts.get(p["id"], {})
        total = sum(counts.values())
        complete = counts.get("complete", 0)
        p["progress"] = {
            "total":       total,
            "pending":     counts.get("pending", 0),
            "diarized":    counts.get("diarized", 0),
            "tts_done":    counts.get("tts_done", 0),
            "assembled":   counts.get("assembled", 0),
            "complete":    complete,
            "error":       counts.get("error", 0),
            "pct_complete": round(complete / total * 100, 1) if total else 0.0,
        }

    return projects
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from state_manager import StateManager; print('ok')"` → prints `ok`.

### Step 2: Update `api.py` to call the new method

In `src/api.py`, replace the `list_projects` endpoint body:

```python
# BEFORE
@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)):
    """All projects with per-project progress, for the UI project picker."""
    projects = sm.list_projects()
    for p in projects:
        p["progress"] = sm.get_progress(p["id"])
    return {"projects": projects}
```

```python
# AFTER
@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)):
    """All projects with per-project progress, for the UI project picker."""
    return {"projects": sm.list_projects_with_progress()}
```

**Verify**: `grep -n "get_progress" src/api.py` → should still appear only in the
`get_project` handler (line ~288), not in `list_projects`.

### Step 3: Run tests

**Verify**: `python tests/test_api.py` → all PASS, exit 0.
**Verify**: `python tests/test_state_manager.py` → all PASS, exit 0.

## Test plan

Add one test to `tests/test_state_manager.py` (model after `test_get_progress`
if it exists, otherwise after the last test):

```python
def test_list_projects_with_progress():
    sm = _tmp_sm()
    pid = sm.seed_project({
        "source_epub": "book.epub",
        "total_chapters": 2,
        "chapters": [
            {"chapter_index": 0, "title": "Ch 1",
             "chunks": [{"chunk_index": 0, "text": "x", "word_count": 1}]},
            {"chapter_index": 1, "title": "Ch 2",
             "chunks": [{"chunk_index": 0, "text": "y", "word_count": 1}]},
        ],
    })
    # Complete one chapter
    chs = sm.get_all_chapters(pid)
    sm.mark_chapter_status(chs[0]["id"], "complete")

    result = sm.list_projects_with_progress()
    assert len(result) == 1
    prog = result[0]["progress"]
    assert prog["total"]    == 2
    assert prog["complete"] == 1
    assert prog["pending"]  == 1
    assert prog["pct_complete"] == 50.0
    print("  PASS test_list_projects_with_progress")
```

Add this test to the `TESTS` list in that file and run:
**Verify**: `python tests/test_state_manager.py` → all PASS including new test.

## Done criteria

- [ ] `list_projects_with_progress()` exists in `src/state_manager.py`
- [ ] `GET /api/projects` no longer calls `get_progress()` in a loop
- [ ] `grep -n "get_progress" src/api.py` → matches only the `get_project` handler, not `list_projects`
- [ ] `python tests/test_api.py` exits 0
- [ ] `python tests/test_state_manager.py` exits 0, including the new test
- [ ] Only `src/state_manager.py` and `src/api.py` are modified
- [ ] `plans/README.md` status row updated to DONE

## STOP conditions

- The current code at `api.py:275-281` does not match the excerpt above.
- `get_progress()` is called from other places in `api.py` beyond `list_projects` — check before removing the loop; do not touch those callers.

## Maintenance notes

If a project is added with thousands of chapters, the aggregation query scans
the full `chapters` table. Adding an index on `chapters.project_id` (beyond the
existing UNIQUE constraint on `(project_id, chapter_index)`) would help, but
the SQLite query planner already uses that composite index for project_id
filtering, so it is not needed now.
