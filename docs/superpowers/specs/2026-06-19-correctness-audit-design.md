# Correctness Audit — Design

**Date:** 2026-06-19
**Status:** Approved (design)
**Origin:** LLM Council 2026-06-19 follow-on. Peer review flagged *trust* as the
real scale bottleneck given past LLM misattribution bugs (ch1842/1848): fast
generation is worthless if every chapter needs a manual listen-through. This is
the automated correctness gate that surfaces *which* chapters need attention.

## Goal

A **read-only** audit that scans the pipeline DB (and finished MP3s) and reports
suspect chapters/lines, so the user knows what to re-listen to or re-run —
without ever mutating or blocking the pipeline. Safe to run mid-backlog on a
power-cut-prone machine because it touches nothing.

Two scopes:
- **Pre-flight** — diarized-but-not-yet-synthesized chapters: catch problems
  (unmapped speakers) *before* a run wastes hours.
- **Post-hoc** — assembled / complete / error chapters: flag what came out wrong.

## Non-goals (v1)

- No UI surfacing (API endpoint only; UI is a later follow-on).
- No mutation of DB or files. No auto-reset, no auto-requeue.
- No per-line WAV duration analysis — per-line WAVs are deleted after assembly
  (`cleanup_wavs=True`), so duration is checked at chapter/MP3 level instead.

## Architecture

Three pieces:

1. **`src/qa_audit.py`** — detection core. Pure functions reading via
   `StateManager`; probes finished MP3s with `ffprobe`. No mutation. Target
   < 350 lines.
2. **`scripts/qa_audit.py`** — CLI wrapper. Human table + `--json`, severity
   filter, exit code. Reusable like `scripts/measure_swap_tax.py`.
3. **`GET /api/qa/audit`** in `src/api.py` — returns the report as JSON
   (read-only).

### Core API

```python
@dataclass
class Finding:
    chapter_index: int
    chapter_id: int
    severity: str      # "high" | "medium" | "low"
    code: str          # stable machine code, see check table
    message: str       # one-line human summary
    detail: dict       # check-specific structured data (counts, speakers, etc.)

@dataclass
class AuditReport:
    findings: list[Finding]
    summary: dict       # counts by severity + code, notes (e.g. ffprobe missing)
    generated_at: str   # ISO8601

def audit_project(sm: StateManager, project_id: int,
                  cfg: AuditConfig = AuditConfig(),
                  chapter_range: "tuple[int,int] | None" = None) -> AuditReport
```

Each check is its own function `check_xxx(...) -> list[Finding]`, so checks are
independently testable and trivial to extend.

### Config

```python
@dataclass
class AuditConfig:
    min_completion_ratio: float = 0.98   # synthesized/total floor for tts_done+
    wpm_expected:         int   = 150    # words per minute for duration estimate
    duration_low_ratio:   float = 0.6    # MP3 secs / expected secs lower bound
    duration_high_ratio:  float = 1.7    # ... upper bound (wide to avoid noise)
    mp3_min_bytes:        int   = 4096   # matches existing assembler guard
    collapse_min_lines:   int   = 20     # speaker_collapse only on chapters >= this
    collapse_pct:         float = 0.97   # >= this fraction one speaker = suspect
```

## Checks

### Post-hoc (status in assembled / complete / error)

| code | trigger | severity |
|------|---------|----------|
| `failed_unmapped` | `lines.status='failed'` whose error mentions "No reference audio" | high |
| `failed_synth` | other `lines.status='failed'` (TTS error) | high |
| `completion_shortfall` | synthesized / total < `min_completion_ratio` | high |
| `empty_text` | line text empty or whitespace-only | medium |
| `mp3_missing` | status=complete but `output_audio_path` absent on disk | high |
| `mp3_tiny` | `output_file_size_bytes` < `mp3_min_bytes` | high |
| `duration_anomaly` | ffprobe MP3 secs vs `words / wpm` outside ratio bounds | medium |
| `chapter_error` | `status='error'` (surface `error_message`) | high |
| `speaker_collapse` | `total_lines >= collapse_min_lines` AND one speaker >= `collapse_pct` of lines | low |

### Pre-flight (status = diarized)

| code | trigger | severity |
|------|---------|----------|
| `preflight_unmapped_hard` | speaker won't resolve AND no `_default` voice → lines will be silently skipped at TTS | high |
| `preflight_unmapped_soft` | speaker won't resolve BUT `_default` exists → will use fallback voice (may sound wrong) | medium |

Pre-flight resolution imports `SPEAKER_ALIASES` from `tts_engine` and mirrors the
3-tier lookup (`{canonical}_{emotion}` → `{canonical}` → `_default`) quietly. The
only part that drifts is the alias table, which is imported directly — so the
check stays faithful to real TTS behavior without invoking the side-effecting
`_resolve_ref_audio` (which prints).

## Data flow & error handling

- MP3 paths resolved via `state_manager._resolve_stored_path` (handles
  CWD-relative legacy rows).
- `ffprobe` absent or failing → `duration_anomaly` skipped, recorded once in
  `summary["notes"]`. Non-fatal; FFmpeg is already a hard dependency.
- `chapter_range` / `--range start end` scopes the audit to a batch.
- Unknown `project_id` → `ValueError` with a clear message.
- Speaker-distribution and failed-line checks are single grouped SQL queries
  over `lines`, not per-chapter loops, to stay fast across 655 chapters.

## CLI / API behavior

- **CLI** (`scripts/qa_audit.py`): args `--db`, `--project NAME`,
  `--range START END`, `--severity {high,medium,low}`, `--json`. Prints a
  table grouped by chapter; exit `0` = clean, `1` = findings present (usable as
  a gate in shell scripts).
- **API** (`GET /api/qa/audit?project_id=...&severity=...`): returns
  `AuditReport` serialized to JSON. Read-only; reuses `get_sm` dependency.

## Testing

`tests/test_qa_audit.py`, following the existing `tests/test_*.py` pattern
(temp-SQLite `StateManager`, no GPU/model). One test per check plus a
clean-project test:

- Seed crafted rows (failed lines, empty text, collapsed speaker, diarized
  chapter with an unmapped speaker with/without `_default`, etc.).
- Monkeypatch the `ffprobe` call to return a controlled duration for
  `duration_anomaly` (both in-band and out-of-band cases).
- Assert exact `code` + `severity` + affected `chapter_index` per finding, and
  that a healthy project yields zero findings.

## File-size discipline

`src/qa_audit.py` is expected ~300 lines (well under the 500 limit). If checks
grow, split detection (`qa_audit.py`) from reporting/formatting later.
