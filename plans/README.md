# Advisor Plans Index

Audit anchored at commit `3831319`. All plans written 2026-06-14.

## Status

| # | Plan | Category | Priority | Effort | Risk | Status |
|---|------|----------|----------|--------|------|--------|
| 001 | [hardcoded-paths](001-hardcoded-paths.md) | bug | P1 | S | LOW | TODO |
| 002 | [list-projects-nplus1](002-list-projects-nplus1.md) | perf | P1 | S | LOW | TODO |
| 003 | [chapter-scan-refactor](003-chapter-scan-refactor.md) | perf | P2 | S | LOW | TODO |
| 004 | [qwen3-no-think-detection](004-qwen3-no-think-detection.md) | bug | P2 | S | LOW | TODO |
| 005 | [pytest-adoption](005-pytest-adoption.md) | dx | P2 | S | LOW | TODO |
| 006 | [db-connection-batching](006-db-connection-batching.md) | perf | P3 | M | MED | TODO |
| 007 | [per-line-inspection-api](007-per-line-inspection-api.md) | direction | P2 | S | LOW | TODO |
| 008 | [batch-chapter-reset](008-batch-chapter-reset.md) | direction | P3 | S | LOW | TODO |

Update the `Status` column as you execute each plan: `TODO → IN PROGRESS → DONE` (or `BLOCKED: reason`).

## Recommended Execution Order

All plans are independent (no plan depends on another). Execute in priority order:

```
1. 001 — hardcoded-paths          (P1, S, zero risk: UI state defaults only)
2. 002 — list-projects-nplus1     (P1, S, zero risk: isolated DB method + 1 endpoint)
3. 004 — qwen3-no-think-detection (P2, S: fixes silent quality regression on renamed GGUFs)
4. 003 — chapter-scan-refactor    (P2, S: isolated StateManager + orchestrator tweak)
5. 005 — pytest-adoption          (P2, S: creates 3 files, touches nothing else)
6. 007 — per-line-inspection-api  (P2, S: read-only endpoint + client helper)
7. 008 — batch-chapter-reset      (P3, S: new endpoint, leaves manual script in place)
8. 006 — db-connection-batching   (P3, M: most structural — do last; MED risk flag)
```

**Rationale for ordering within P2**: 004 first because it fixes a silent correctness issue (bad LLM output on renamed models). 003 and 005 are clean-up; 007 and 008 add surface area. 006 last because it's the only plan rated MED risk (touches the hot TTS loop).

## Dependency Graph

```
001 ──┐
002 ──┤
003 ──┤
004 ──┤─── independent, any order
005 ──┤
006 ──┤
007 ──┤
008 ──┘
```

No plan modifies a file that another plan also modifies, so they can be executed in any order and even in parallel branches without merge conflicts — with one exception: **plans 007 and 008 both modify `src/api.py` and `ui/lib/api.ts`**. If running concurrently, finish one before starting the other, or cherry-pick carefully.

## What Was Audited

Standard-effort audit. Covered:

- **Correctness / bugs**: M3 `llm_director.py`, M4 `tts_engine.py`, M2 `state_manager.py`, M7 `api.py`, M8 `ui/app/page.tsx`
- **Performance**: `api.py` list endpoint, `orchestrator.py` chapter scan, `state_manager.py` per-line writes
- **Tests**: all `tests/test_*.py` files — runner pattern, discoverability
- **DX / tooling**: `pytest.ini` absence, `requirements-dev.txt` absence
- **Direction**: missing batch-reset endpoint, missing per-line read API

**Not audited in this pass**: `epub_parser.py` (M1), `audio_assembler.py` (M5) beyond the FFmpeg escaping check, security surface (file-upload endpoint, path traversal), `ui/components/` and `ui/hooks/` in detail, EPUB parsing edge cases, i18n/unicode handling in diarization output.

## Considered and Rejected

| Finding | Why Rejected |
|---------|--------------|
| **FFmpeg `'\''` escaping in `audio_assembler.py:36–38`** | Initially flagged as wrong bash-escaping. On re-analysis: `'\''` is correct POSIX-style escaping for the FFmpeg concat demuxer's `file` directive format, which uses POSIX shell quoting rules. The FFmpeg docs confirm this. Not a bug. |
