# Plan 006: Batch TTS line DB writes to reduce per-line connection overhead

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- src/state_manager.py src/tts_engine.py`
> On any mismatch with the excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

`TTSEngine.process_chapter()` calls `sm.mark_line_tts_done(line_id, path)`
after every synthesised line. Each call opens a new SQLite connection, writes
one row, commits, and closes. For a chapter with 200 lines that is 200
connection open/close cycles during synthesis.

On Windows, SQLite connection setup is measurable (file open, journal mode
check, WAL init). The overhead per connection is small (~1–3 ms) but adds up
to ~200–600 ms per chapter — less than a single TTS synthesis step (15–20 s)
but wasted time on the DB layer.

The fix adds a `mark_lines_tts_done(updates)` batch method to `StateManager`
and calls it from `TTSEngine` in configurable micro-batches (default: every
`db_flush_every` lines, configurable via `_DEFAULT_CFG`). The per-line
`mark_line_tts_done` is preserved; only the TTS hot loop changes.

**Resume safety**: The pipeline can resume from any successfully synthesised
line if TTS crashes mid-chapter (the DB tracks which lines have `status='tts_done'`).
Micro-batching means up to `db_flush_every - 1` lines re-synthesise on resume
after a mid-batch crash. At the default of 10, at most 9 lines would re-do,
which is acceptable.

## Current state

- `src/state_manager.py:405-410` — per-line write:

```python
# src/state_manager.py:405-410
def mark_line_tts_done(self, line_id: int, audio_path: str) -> None:
    with self._conn() as conn:
        conn.execute(
            """UPDATE lines SET status='tts_done', audio_path=? WHERE id=?""",
            (audio_path, line_id),
        )
```

- `src/tts_engine.py:507-509` — called once per successfully synthesised line:

```python
# src/tts_engine.py:507-509
if wav_bytes:
    audio_path.write_bytes(wav_bytes)
    self.sm.mark_line_tts_done(line["id"], str(audio_path))
```

- `src/tts_engine.py:211-229` — `_DEFAULT_CFG` (abridged):

```python
# src/tts_engine.py:211-229
_DEFAULT_CFG = {
    "use_fp16":       False,
    "use_deepspeed":  False,
    "use_cuda_kernel": False,
    "max_retries":    2,
    "max_line_chars": 400,
    "emo_alpha_scale": 1.0,
    "config_name":    "config.yaml",
    "max_text_tokens_per_segment": 200,
    "num_beams":      3,
}
```

## Commands you will need

| Purpose      | Command                           | Expected on success  |
|--------------|-----------------------------------|----------------------|
| TTS tests    | `python tests/test_tts_engine.py` | all PASS, exit 0     |
| State tests  | `python tests/test_state_manager.py` | all PASS, exit 0  |

## Scope

**In scope**:
- `src/state_manager.py` — add `mark_lines_tts_done(updates)`
- `src/tts_engine.py` — add `db_flush_every` to `_DEFAULT_CFG`; update
  `process_chapter` to accumulate and flush in micro-batches

**Out of scope**:
- `mark_line_tts_done` — leave it unchanged; it is still used by
  `mark_line_failed` callers and tests that call it directly.
- Any other module or test file.

## Git workflow

- Branch: `advisor/006-db-connection-batching`
- One commit: `perf(tts): batch DB line writes to reduce per-line connection overhead`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `mark_lines_tts_done` batch method to `StateManager`

In `src/state_manager.py`, insert immediately after `mark_line_tts_done`
(after line 410):

```python
def mark_lines_tts_done(self, updates: "list[tuple[int, str]]") -> None:
    """Batch update multiple lines to tts_done in one connection.

    updates: [(line_id, audio_path), ...]
    """
    if not updates:
        return
    with self._conn() as conn:
        conn.executemany(
            "UPDATE lines SET status='tts_done', audio_path=? WHERE id=?",
            [(path, line_id) for line_id, path in updates],
        )
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from state_manager import StateManager; print(hasattr(StateManager, 'mark_lines_tts_done'))"` → `True`.

### Step 2: Add `db_flush_every` to TTS `_DEFAULT_CFG`

In `src/tts_engine.py`, add one key to `_DEFAULT_CFG`:

```python
"db_flush_every": 10,   # write tts_done updates to DB every N lines (resume granularity)
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from tts_engine import _DEFAULT_CFG; print('db_flush_every' in _DEFAULT_CFG)"` → `True`.

### Step 3: Update `process_chapter` to flush in micro-batches

In `src/tts_engine.py`, modify `process_chapter`. Find the section that marks
a successful line (lines 507–509) and the containing for-loop. The change adds
a pending-updates buffer that is flushed every `db_flush_every` lines and
unconditionally at the end.

The key structural change inside the `for processed, line in enumerate(lines, start=1):` loop:

**BEFORE** (line 507–509):
```python
if wav_bytes:
    audio_path.write_bytes(wav_bytes)
    self.sm.mark_line_tts_done(line["id"], str(audio_path))
    success_count += 1
```

**AFTER**:
```python
if wav_bytes:
    audio_path.write_bytes(wav_bytes)
    _pending_db.append((line["id"], str(audio_path)))
    success_count += 1
    if len(_pending_db) >= self.cfg["db_flush_every"]:
        self.sm.mark_lines_tts_done(_pending_db)
        _pending_db.clear()
```

And before the for-loop (just after `total = len(lines)`), add:
```python
_pending_db: list[tuple[int, str]] = []
```

And after the for-loop (before `self.sm.mark_chapter_status`), add the final flush:
```python
if _pending_db:
    self.sm.mark_lines_tts_done(_pending_db)
    _pending_db.clear()
```

The `mark_line_failed` call (already in the loop, line 515) is unchanged —
failures are still written immediately (one-off per failed line, which is rare).

**Verify**: `grep -n "mark_line_tts_done\b" src/tts_engine.py` → no matches
(the per-line call is gone; only `mark_lines_tts_done` in the flush path remains).

### Step 4: Run tests

**Verify**: `python tests/test_tts_engine.py` → all PASS, exit 0.
**Verify**: `python tests/test_state_manager.py` → all PASS, exit 0.

## Test plan

Add to `tests/test_state_manager.py`:

```python
def test_mark_lines_tts_done_batch():
    sm  = _tmp_sm()
    pid = sm.seed_project({
        "source_epub": "book.epub",
        "total_chapters": 1,
        "chapters": [{"chapter_index": 0, "title": "Ch", "chunks":
                       [{"chunk_index": 0, "text": "x", "word_count": 1}]}],
    })
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    sm.save_diarized_lines(ch_id, [
        {"line_index": 0, "speaker": "Narrator", "text": "A.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Narrator", "text": "B.", "emotion": "neutral"},
    ])
    lines = sm.get_pending_tts_lines(ch_id)
    assert len(lines) == 2

    updates = [(lines[0]["id"], "/fake/a.wav"), (lines[1]["id"], "/fake/b.wav")]
    sm.mark_lines_tts_done(updates)

    done = sm.get_lines_for_chapter(ch_id)
    assert all(l["status"] == "tts_done" for l in done)
    assert done[0]["audio_path"] == "/fake/a.wav"
    print("  PASS test_mark_lines_tts_done_batch")
```

Add to `TESTS` list and run. Also verify the existing TTS engine tests (which
use the `_synthesize` monkeypatch) still pass without changes.

**Verify**: `python tests/test_state_manager.py` → all PASS including new test.

## Done criteria

- [ ] `mark_lines_tts_done` exists in `src/state_manager.py`
- [ ] `"db_flush_every"` key exists in `_DEFAULT_CFG` in `src/tts_engine.py`
- [ ] `grep -n "mark_line_tts_done\b" src/tts_engine.py` → no matches (per-line call removed from process_chapter)
- [ ] `python tests/test_tts_engine.py` exits 0
- [ ] `python tests/test_state_manager.py` exits 0 including new test
- [ ] Only `src/state_manager.py` and `src/tts_engine.py` modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- A test that exercised `mark_line_tts_done` in `process_chapter` fails — look
  for tests that check per-line DB state mid-synthesis; adjust the check to
  account for the batch flush.
- The per-line `mark_line_failed` call is accidentally changed — it must remain
  per-line (write immediately on failure).
- `process_chapter` produces a different `success_count` than before the change
  in any existing test.

## Maintenance notes

If the chapter resume path is ever made more granular (e.g. restart from the
last successfully synthesised line within a chapter), reduce `db_flush_every`
or set it to 1 to restore per-line durability. The `db_flush_every` config key
allows this tuning without code changes: pass `cfg={"db_flush_every": 1}` to
`TTSEngine` to restore the old behaviour.

The `mark_line_tts_done` method is still in `StateManager` and used by tests
that call it directly — do not remove it.
