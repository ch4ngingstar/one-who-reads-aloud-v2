# Plan 004: Broaden Qwen3 no-think detection to be config-overridable and match renamed files

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 3831319..HEAD -- src/llm_director.py`
> On any mismatch with the excerpts below, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `3831319`, 2026-06-14

## Why this matters

The Qwen3 model family requires `/no_think` appended to the user prompt to
disable its hybrid chain-of-thought mode. Without it, Qwen3 produces a
`<think>...</think>` preamble before the JSON output. The current detection
checks `"qwen3" in self.model_path.name.lower()`. This is fragile:

1. If the user renames the GGUF (e.g. to `local_llm.gguf` or stores it under
   a version-neutral name), the check silently fails.
2. Future Qwen variants (e.g. `qwen-3-32b`) using a hyphen would also miss it.

When thinking mode is on, `_extract_json_block` usually still finds the JSON
(it searches for the first `{`), but if the `<think>` block itself contains
braces the parser may extract the wrong JSON and trigger retries at elevated
temperature, reducing label quality. Adding an explicit `no_think` config key
(default: `None` = auto-detect) lets users override detection regardless of
filename, and broadening the auto-detect pattern covers common naming variants.

## Current state

- `src/llm_director.py:82-98` — `_DEFAULT_CFG` dict (abridged):

```python
# src/llm_director.py:82-98
_DEFAULT_CFG = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.2,
    "top_p":        0.8,
    "max_tokens":   4096,
    "retry_temp":   0.5,
    "max_retries":  3,
}
```

- `src/llm_director.py:530-554` — `_process_chunk` method (key lines 536-537):

```python
# src/llm_director.py:536-537
if "qwen3" in self.model_path.name.lower():
    user_msg += "\n/no_think"
```

## Commands you will need

| Purpose      | Command                            | Expected on success  |
|--------------|------------------------------------|----------------------|
| LLM tests    | `python tests/test_llm_director.py`| all PASS, exit 0     |

## Scope

**In scope**:
- `src/llm_director.py` — `_DEFAULT_CFG` dict and `_process_chunk` method

**Out of scope**:
- Anything in TTS, assembler, or UI — this is purely LLM director logic.

## Git workflow

- Branch: `advisor/004-qwen3-no-think-detection`
- One commit: `fix(llm): make no_think detection config-overridable and match qwen-3 naming`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add `no_think` key to `_DEFAULT_CFG`

In `src/llm_director.py`, add one entry to `_DEFAULT_CFG`:

```python
# _DEFAULT_CFG — add after "max_retries":
"no_think": None,   # None = auto-detect from model filename; True/False to force
```

The full updated dict (replace the existing one):

```python
_DEFAULT_CFG = {
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    "temperature":  0.2,
    "top_p":        0.8,
    "max_tokens":   4096,
    "retry_temp":   0.5,
    "max_retries":  3,
    "no_think":     None,   # None = auto-detect from model filename; True/False to force
}
```

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from llm_director import _DEFAULT_CFG; print('no_think' in _DEFAULT_CFG)"` → `True`.

### Step 2: Replace the filename check in `_process_chunk`

In `src/llm_director.py`, replace lines 536–537:

```python
# BEFORE
if "qwen3" in self.model_path.name.lower():
    user_msg += "\n/no_think"
```

```python
# AFTER
_no_think = self.cfg.get("no_think")
if _no_think is None:
    _model_name = self.model_path.name.lower()
    _no_think = "qwen3" in _model_name or "qwen-3" in _model_name
if _no_think:
    user_msg += "\n/no_think"
```

**Verify**: `grep -n "qwen3" src/llm_director.py` → matches only the detection
line (`"qwen3" in _model_name`) — not the old standalone `if "qwen3" in ...` line.

### Step 3: Run tests

**Verify**: `python tests/test_llm_director.py` → all PASS, exit 0.

## Test plan

The existing LLM director tests monkeypatch `_call_llm` so no model is
loaded. Add two new tests to `tests/test_llm_director.py` exercising the
detection logic:

```python
def test_no_think_auto_detect_qwen3():
    """auto-detect triggers for 'qwen3' and 'qwen-3' filenames."""
    from pathlib import Path
    from llm_director import LLMDirector, _DEFAULT_CFG

    for name in ["Qwen3-14B-Q4_K_M.gguf", "qwen-3-32b-instruct.gguf", "QWEN3.gguf"]:
        d = LLMDirector.__new__(LLMDirector)
        d.model_path = Path(name)
        d.cfg = {**_DEFAULT_CFG}   # no_think = None → auto
        d.sm = None
        d.speakers = []
        d._allowed = set()
        d._system_prompt = ""
        d._llm = None
        d._grammar = None

        user_msg_base = "0 [P] Some text."
        # Simulate _process_chunk reaching the detection — call the relevant
        # logic inline rather than the full method (which needs a loaded model).
        _model_name = d.model_path.name.lower()
        _no_think = d.cfg.get("no_think")
        if _no_think is None:
            _no_think = "qwen3" in _model_name or "qwen-3" in _model_name
        assert _no_think, f"no_think should be True for {name}"
    print("  PASS test_no_think_auto_detect_qwen3")


def test_no_think_manual_override():
    """cfg no_think=True forces the flag regardless of filename."""
    from pathlib import Path
    from llm_director import LLMDirector, _DEFAULT_CFG

    d = LLMDirector.__new__(LLMDirector)
    d.model_path = Path("local_llm.gguf")   # no 'qwen3' in name
    d.cfg = {**_DEFAULT_CFG, "no_think": True}

    _no_think = d.cfg.get("no_think")
    if _no_think is None:
        _no_think = "qwen3" in d.model_path.name.lower()
    assert _no_think, "no_think should be True when forced via cfg"
    print("  PASS test_no_think_manual_override")
```

Add both to the `TESTS` list and run.

**Verify**: `python tests/test_llm_director.py` → all PASS including two new tests.

## Done criteria

- [ ] `_DEFAULT_CFG` contains `"no_think": None`
- [ ] `_process_chunk` uses the three-line detection block (cfg override → auto-detect with `"qwen-3"` variant)
- [ ] `grep -n "\"qwen3\" in self.model_path" src/llm_director.py` → no matches (old one-liner is gone)
- [ ] `python tests/test_llm_director.py` exits 0, including two new tests
- [ ] Only `src/llm_director.py` is modified
- [ ] `plans/README.md` status updated to DONE

## STOP conditions

- The code at lines 536–537 does not match the `"qwen3" in self.model_path...` excerpt (file drifted).
- An existing test fails after the change.

## Maintenance notes

If Qwen4 or another thinking-mode model family is adopted, extend the
auto-detect condition rather than adding another one-off check. Alternatively,
the `no_think` config key can be set explicitly in the orchestrator's
`llm_cfg` dict, bypassing the filename heuristic entirely.
