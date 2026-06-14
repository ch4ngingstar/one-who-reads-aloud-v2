# Plan 005: Adopt pytest for backend test discovery and single-command runs

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- tests/`
> On any new or changed test file, reconcile with the plan before continuing.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

All 7 backend test files (`tests/test_*.py`) use a home-rolled runner — each
file has a `TESTS = [...]` list and a `if __name__ == "__main__":` block. There
is no way to run all tests with one command, no pytest plugin support, and no
standard exit code for CI. Every file must be run separately.

Pytest already discovers `test_*` functions, so minimal change is needed: add
a `pytest.ini` to set the `testpaths` and Python path, and add a
`tests/conftest.py` to handle the `sys.path.insert` that each file currently
does. The bespoke `if __name__ == "__main__"` runners are left in place — they
continue to work for manual individual-file runs.

## Current state

Each test file begins with:
```python
# tests/test_api.py:1-5  (representative; all 7 files do this)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
```

There is no `pytest.ini`, no `pyproject.toml`, no `conftest.py`, and `pytest`
is not listed in `requirements.txt`.

## Commands you will need

| Purpose         | Command                     | Expected on success       |
|-----------------|-----------------------------|---------------------------|
| Install pytest  | `pip install pytest`        | exit 0                    |
| Run all tests   | `pytest`                    | all PASS, exit 0          |
| Single file     | `pytest tests/test_api.py`  | all PASS, exit 0          |

## Scope

**In scope** (only files you create):
- `pytest.ini` — at the repo root
- `tests/conftest.py` — pytest conftest for path setup

**Out of scope** (do NOT modify):
- Any `tests/test_*.py` file — leave them exactly as they are, including their
  custom `TESTS` lists and `if __name__ == "__main__"` runners. Pytest discovers
  the `test_*` functions automatically without removing the manual runner.
- `requirements.txt` — pytest is a dev dependency; add it to a new
  `requirements-dev.txt` (create if absent) rather than polluting the runtime
  requirements.

## Git workflow

- Branch: `advisor/005-pytest-adoption`
- One commit: `dx: add pytest.ini and conftest for single-command test runs`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Create `pytest.ini` at the repo root

```ini
[pytest]
testpaths = tests
pythonpath = src
```

`pythonpath = src` (pytest ≥ 7 / `pytest-pythonpath` ≥ 0.7) inserts `src/`
into `sys.path`, replicating the `sys.path.insert` each test does. This
requires pytest ≥ 7.0.

**Verify**: `pytest --co -q 2>&1 | head -5` — should list collected test IDs
without "ModuleNotFoundError".

### Step 2: Create `tests/conftest.py`

```python
# tests/conftest.py
# Empty — pytest.ini's pythonpath setting handles sys.path.
# Add shared fixtures here if needed in the future.
```

**Verify**: `ls tests/conftest.py` → file exists.

### Step 3: Create `requirements-dev.txt`

```
pytest>=7.0
```

**Verify**: `cat requirements-dev.txt` → contains `pytest>=7.0`.

### Step 4: Full run

**Verify**: `pytest` (from repo root) → all tests collected and PASS, exit 0.

The count should match the sum of tests across all 7 files. If any test was
previously silently broken under the manual runner (e.g. an exception escaped
the try/except in the runner), it will surface here as a failure. Fix only
genuine failures — do not suppress.

**Verify**: `pytest tests/test_api.py tests/test_orchestrator.py -v` → both
files run, all PASS.

## Test plan

No new tests are written. The goal is that all existing tests pass under
pytest. The new test count must equal the number of functions discovered
(each `test_*` function in each file).

If pytest reports fewer tests than expected (e.g. the custom `TESTS` list
contains a function not named `test_*`), rename that function to follow the
`test_` prefix convention. Check each file for any function in the `TESTS`
list that does not start with `test_`.

**Verify**: `pytest --co -q | grep "<Function" | wc -l` — count should be
≥ 60 (the sum of test functions across all 7 files based on the current
codebase).

## Done criteria

- [ ] `pytest.ini` exists at repo root with `testpaths = tests` and `pythonpath = src`
- [ ] `tests/conftest.py` exists (even if empty)
- [ ] `requirements-dev.txt` exists with `pytest>=7.0`
- [ ] `pytest` (from repo root) exits 0 with all tests passing
- [ ] `pytest tests/test_api.py` exits 0
- [ ] `pytest tests/test_orchestrator.py` exits 0
- [ ] No `tests/test_*.py` file was modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- `pytest --co` raises `ModuleNotFoundError` for any `src/` module — the
  `pythonpath = src` setting requires pytest ≥ 7; verify with
  `pytest --version` and upgrade if below 7.0.
- A test that passed under the manual runner fails under pytest — investigate
  before moving on; do not mark as skip or xfail without understanding why.
- Any `test_*.py` file is in a state where a function in its `TESTS` list is
  not named with a `test_` prefix — rename only that function (prefix with
  `test_`), and confirm the manual runner still works.

## Maintenance notes

The `if __name__ == "__main__"` blocks and `TESTS` lists in each test file are
now redundant for CI but harmless. Leave them for developers who prefer running
a single file manually with `python tests/test_api.py`. If the test suite
grows significantly, consider splitting into `tests/unit/` and
`tests/integration/` subdirectories — update `testpaths` in `pytest.ini` when
that happens.
