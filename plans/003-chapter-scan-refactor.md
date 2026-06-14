# Plan 003: Add get_chapter_by_id to StateManager; eliminate full-chapter-list scan in orchestrator

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- src/state_manager.py src/orchestrator.py`
> On any mismatch with the excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

After each chapter finishes processing, the orchestrator fetches the audio path
that was just written by the assembler. It does this by loading **every chapter
in the project** and searching for the one it just processed:

```python
# src/orchestrator.py:285-287
refreshed   = self.sm.get_all_chapters(self._project_id)
ch_row      = next(c for c in refreshed if c["id"] == ch_id)
audio_path  = ch_row.get("output_audio_path", "")
```

Shadow Slave has ~1800 chapters. After chapter 900 completes, this loads and
searches 1800 rows to find one. The fix is a targeted `get_chapter_by_id()`
query that returns one row. Total savings over a full run: 1800 × O(n) scans
→ 1800 × O(1) lookups.

## Current state

- `src/state_manager.py` — no `get_chapter_by_id` method exists. The relevant
  existing method for comparison is `get_all_chapters`:

```python
# src/state_manager.py:257-265
def get_all_chapters(self, project_id: int) -> list:
    with self._conn() as conn:
        rows = conn.execute(
            """SELECT * FROM chapters
               WHERE project_id = ?
               ORDER BY chapter_index""",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- `src/orchestrator.py` — `_run_chapter` method, lines 285–295 (abridged):

```python
# src/orchestrator.py:285-295
refreshed   = self.sm.get_all_chapters(self._project_id)
ch_row      = next(c for c in refreshed if c["id"] == ch_id)
audio_path  = ch_row.get("output_audio_path", "")
elapsed     = round(time.time() - ch_t0, 1)

self.sm.mark_chapter_status(ch_id, "complete", processing_seconds=elapsed)

self._emit("chapter_done",
           chapter_id=ch_id,
           audio_path=audio_path,
           elapsed_s=elapsed)
```

- Conv: `None | dict` is the standard return for a "not found" lookup in this
  codebase (see `get_project` at `state_manager.py:242-247`). Match that
  pattern.

## Commands you will need

| Purpose          | Command                               | Expected on success  |
|------------------|---------------------------------------|----------------------|
| State tests      | `python tests/test_state_manager.py`  | all PASS, exit 0     |
| Orchestrator tests | `python tests/test_orchestrator.py` | all PASS, exit 0     |

## Scope

**In scope**:
- `src/state_manager.py` — add `get_chapter_by_id(chapter_id: int)`
- `src/orchestrator.py` — replace the `get_all_chapters` scan in `_run_chapter`

**Out of scope**:
- All other callers of `get_all_chapters` — the method stays and is still used
  elsewhere (setup, chapter range filtering, etc.).

## Git workflow

- Branch: `advisor/003-chapter-scan-refactor`
- One commit: `perf(orchestrator): replace chapter-list scan with targeted get_chapter_by_id lookup`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `get_chapter_by_id` to `StateManager`

Insert this method in `src/state_manager.py` immediately after
`get_all_chapters` (after line 265):

```python
def get_chapter_by_id(self, chapter_id: int) -> "dict | None":
    """Fetch a single chapter row by its primary key. Returns None if not found."""
    with self._conn() as conn:
        row = conn.execute(
            "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
        return dict(row) if row else None
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from state_manager import StateManager; print(hasattr(StateManager, 'get_chapter_by_id'))"` → `True`.

### Step 2: Replace the scan in `_run_chapter`

In `src/orchestrator.py`, replace the two-line scan (lines 285–287):

```python
# BEFORE
refreshed   = self.sm.get_all_chapters(self._project_id)
ch_row      = next(c for c in refreshed if c["id"] == ch_id)
audio_path  = ch_row.get("output_audio_path", "")
```

```python
# AFTER
ch_row     = self.sm.get_chapter_by_id(ch_id) or {}
audio_path = ch_row.get("output_audio_path", "")
```

Note: `or {}` ensures `audio_path` is `""` even on the (impossible in practice)
case where the row disappears between assemble and this call. This matches the
existing fallback behaviour.

**Verify**: `grep -n "get_all_chapters" src/orchestrator.py` → no matches
(the scan is gone; `get_all_chapters` is only called in `_chapters_to_process`
and `_setup`, not in `_run_chapter`).

### Step 3: Run tests

**Verify**: `python tests/test_orchestrator.py` → all PASS, exit 0.
**Verify**: `python tests/test_state_manager.py` → all PASS, exit 0.

## Test plan

Add to `tests/test_state_manager.py`:

```python
def test_get_chapter_by_id():
    sm  = _tmp_sm()  # use the existing _tmp_sm() helper in that file
    pid = sm.seed_project({
        "source_epub": "book.epub",
        "total_chapters": 1,
        "chapters": [
            {"chapter_index": 0, "title": "Prologue",
             "chunks": [{"chunk_index": 0, "text": "x", "word_count": 1}]},
        ],
    })
    ch = sm.get_all_chapters(pid)[0]

    found = sm.get_chapter_by_id(ch["id"])
    assert found is not None
    assert found["id"] == ch["id"]
    assert found["title"] == "Prologue"

    assert sm.get_chapter_by_id(999999) is None
    print("  PASS test_get_chapter_by_id")
```

Add to the `TESTS` list and run.

**Verify**: `python tests/test_state_manager.py` → all PASS including new test.

## Done criteria

- [ ] `get_chapter_by_id` method exists in `src/state_manager.py`
- [ ] `grep -n "get_all_chapters" src/orchestrator.py` shows no match inside `_run_chapter`
- [ ] `python tests/test_orchestrator.py` exits 0
- [ ] `python tests/test_state_manager.py` exits 0, including new test
- [ ] Only `src/state_manager.py` and `src/orchestrator.py` are modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- `get_all_chapters` inside `_run_chapter` appears at a different line than
  expected (drift) — find and fix the correct location before replacing.
- A test that relied on the `refreshed` list breaks after the change.

## Maintenance notes

If the chapter pipeline ever needs more data about the completed chapter
(beyond `output_audio_path`), `get_chapter_by_id` returns the full row —
no changes needed. If a chapter needs to be "re-fetched mid-flight" for
any other purpose, use `get_chapter_by_id`, not `get_all_chapters`.
