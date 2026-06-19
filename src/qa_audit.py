"""
Correctness Audit (read-only QA gate)
=====================================
Scans the pipeline DB (and finished MP3s) and reports suspect chapters/lines so
the user knows what to re-listen to or re-run. NEVER mutates the DB or files and
NEVER blocks the pipeline — safe to run mid-backlog on a power-cut-prone machine.

Two scopes:
  - PRE-FLIGHT  (status='diarized'): catch unmapped speakers BEFORE a run wastes
    hours synthesising lines that will be skipped or land on the wrong voice.
  - POST-HOC    (status in assembled/complete/error): flag what came out wrong —
    failed lines, completion shortfalls, missing/tiny MP3s, duration anomalies,
    and single-speaker collapse (the LLM-misattribution failure class).

All DB access goes through StateManager's public read methods (no bypass).
ffprobe (already a hard dependency via FFmpeg) measures MP3 duration; if it is
absent the duration check is skipped and noted in the report — never fatal.

Usage:
    from qa_audit import audit_project, AuditConfig
    report = audit_project(sm, project_id)
    for f in report.findings:
        print(f.severity, f.code, f.chapter_index, f.message)
"""

import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from state_manager import StateManager, _resolve_stored_path
# SPEAKER_ALIASES is the only part of voice resolution that drifts; import it
# directly so the pre-flight check stays faithful to real TTS behavior. The
# heavy indextts import in tts_engine is lazy (inside a method), so this is cheap.
from tts_engine import SPEAKER_ALIASES


# ── Severity ──────────────────────────────────────────────────────────────────
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Chapter statuses each scope applies to.
_POSTHOC_STATUSES = {"tts_done", "assembled", "complete", "error"}
_SYNTH_DONE_STATUSES = {"tts_done", "assembled", "complete"}


@dataclass
class AuditConfig:
    min_completion_ratio: float = 0.98   # synthesized/total floor for synth-done chapters
    wpm_expected:         int   = 150    # words per minute for duration estimate
    duration_low_ratio:   float = 0.6    # MP3 secs / expected secs lower bound
    duration_high_ratio:  float = 1.7    # ... upper bound (wide to avoid noise)
    mp3_min_bytes:        int   = 4096   # matches the assembler's existing guard
    collapse_min_lines:   int   = 20     # speaker_collapse only on chapters >= this
    collapse_pct:         float = 0.97   # >= this fraction one speaker = suspect


@dataclass
class Finding:
    chapter_index: int
    chapter_id:    int
    severity:      str          # "high" | "medium" | "low"
    code:          str          # stable machine code (see module docstring)
    message:       str          # one-line human summary
    detail:        dict = field(default_factory=dict)


@dataclass
class AuditReport:
    findings:     list          # list[Finding]
    summary:      dict
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "findings": [asdict(f) for f in self.findings],
            "summary": self.summary,
            "generated_at": self.generated_at,
        }


# ── Voice resolution (quiet mirror of TTSEngine._resolve_ref_audio) ────────────

def _resolve_category(speaker: str, emotion: str, voice_map: dict) -> str:
    """
    Classify how a (speaker, emotion) would resolve at TTS time, WITHOUT the
    side-effecting prints of the real resolver:
      "mapped"   — a dedicated voice (emotion clip or canonical) exists
      "fallback" — only the _default voice would catch it (quality risk)
      "unmapped" — nothing resolves; the line would be silently skipped
    Mirrors the 3-tier lookup in TTSEngine._resolve_ref_audio.
    """
    normalised = speaker.strip().title()
    canonical  = SPEAKER_ALIASES.get(normalised, normalised)

    if canonical == "_default":
        return "mapped" if "_default" in voice_map else "unmapped"

    if f"{canonical}_{emotion}" in voice_map or canonical in voice_map:
        return "mapped"
    if "_default" in voice_map:
        return "fallback"
    return "unmapped"


# ── ffprobe ────────────────────────────────────────────────────────────────────

def _probe_duration_s(path: Path) -> Optional[float]:
    """MP3 duration in seconds via ffprobe, or None if ffprobe/file unavailable."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (FileNotFoundError, ValueError, subprocess.SubprocessError):
        pass
    return None


def _ffprobe_available() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


# ── Per-chapter checks ──────────────────────────────────────────────────────────

def _check_preflight(chapter: dict, lines: list, voice_map: dict) -> list:
    """Diarized chapters: flag speakers that won't resolve at TTS time."""
    findings = []
    hard, soft = {}, {}   # speaker -> count
    for ln in lines:
        cat = _resolve_category(ln["speaker"], ln["emotion"], voice_map)
        if cat == "unmapped":
            hard[ln["speaker"]] = hard.get(ln["speaker"], 0) + 1
        elif cat == "fallback":
            soft[ln["speaker"]] = soft.get(ln["speaker"], 0) + 1

    if hard:
        findings.append(_finding(
            chapter, "high", "preflight_unmapped_hard",
            f"{sum(hard.values())} line(s) across {len(hard)} speaker(s) have no "
            f"voice and no _default fallback — they will be SKIPPED at TTS.",
            {"speakers": hard},
        ))
    if soft:
        findings.append(_finding(
            chapter, "medium", "preflight_unmapped_soft",
            f"{sum(soft.values())} line(s) across {len(soft)} speaker(s) will use "
            f"the _default fallback voice (may sound wrong).",
            {"speakers": soft},
        ))
    return findings


def _check_failed_lines(chapter: dict, lines: list) -> list:
    findings = []
    unmapped, synth = [], []
    for ln in lines:
        if ln["status"] != "failed":
            continue
        msg = ln.get("error_message") or ""
        if "No reference audio" in msg:
            unmapped.append(ln["line_index"])
        else:
            synth.append(ln["line_index"])
    if unmapped:
        findings.append(_finding(
            chapter, "high", "failed_unmapped",
            f"{len(unmapped)} line(s) skipped — no reference audio for speaker.",
            {"line_indexes": unmapped[:50]},
        ))
    if synth:
        findings.append(_finding(
            chapter, "high", "failed_synth",
            f"{len(synth)} line(s) failed TTS synthesis.",
            {"line_indexes": synth[:50]},
        ))
    return findings


def _check_completion(chapter: dict, lines: list, cfg: AuditConfig) -> list:
    total = len(lines)
    if total == 0:
        return []
    synthesized = sum(1 for ln in lines if ln["status"] == "tts_done")
    ratio = synthesized / total
    if ratio < cfg.min_completion_ratio:
        return [_finding(
            chapter, "high", "completion_shortfall",
            f"only {synthesized}/{total} lines synthesised "
            f"({ratio:.0%} < {cfg.min_completion_ratio:.0%}).",
            {"synthesized": synthesized, "total": total, "ratio": round(ratio, 3)},
        )]
    return []


def _check_empty_text(chapter: dict, lines: list) -> list:
    empty = [ln["line_index"] for ln in lines if not (ln.get("text") or "").strip()]
    if empty:
        return [_finding(
            chapter, "medium", "empty_text",
            f"{len(empty)} line(s) have empty/whitespace text.",
            {"line_indexes": empty[:50]},
        )]
    return []


def _check_speaker_collapse(chapter: dict, lines: list, cfg: AuditConfig) -> list:
    total = len(lines)
    if total < cfg.collapse_min_lines:
        return []
    counts: dict[str, int] = {}
    for ln in lines:
        counts[ln["speaker"]] = counts.get(ln["speaker"], 0) + 1
    dominant, n = max(counts.items(), key=lambda kv: kv[1])
    pct = n / total
    if pct >= cfg.collapse_pct:
        return [_finding(
            chapter, "low", "speaker_collapse",
            f"{pct:.0%} of {total} lines are '{dominant}' — possible "
            f"diarization misattribution.",
            {"speaker": dominant, "count": n, "total": total, "pct": round(pct, 3)},
        )]
    return []


def _check_mp3(chapter: dict, lines: list, cfg: AuditConfig,
               ffprobe_ok: bool) -> list:
    """MP3 presence/size/duration checks for completed chapters."""
    findings = []
    raw_path = chapter.get("output_audio_path")
    if not raw_path:
        return [_finding(chapter, "high", "mp3_missing",
                         "chapter is complete but has no output audio path.")]
    path = _resolve_stored_path(raw_path)
    if not path.exists():
        return [_finding(chapter, "high", "mp3_missing",
                         f"output MP3 not found on disk: {raw_path}",
                         {"path": str(raw_path)})]

    size = path.stat().st_size
    if size < cfg.mp3_min_bytes:
        findings.append(_finding(
            chapter, "high", "mp3_tiny",
            f"output MP3 is only {size} bytes (< {cfg.mp3_min_bytes}).",
            {"bytes": size}))
        return findings  # a tiny file's duration is meaningless

    if ffprobe_ok:
        actual = _probe_duration_s(path)
        words  = sum(len((ln.get("text") or "").split()) for ln in lines)
        if actual is not None and words > 0:
            expected = words / cfg.wpm_expected * 60.0
            ratio = actual / expected if expected > 0 else 0.0
            if ratio < cfg.duration_low_ratio or ratio > cfg.duration_high_ratio:
                findings.append(_finding(
                    chapter, "medium", "duration_anomaly",
                    f"MP3 is {actual:.0f}s but ~{expected:.0f}s expected from "
                    f"{words} words (ratio {ratio:.2f}).",
                    {"actual_s": round(actual, 1), "expected_s": round(expected, 1),
                     "words": words, "ratio": round(ratio, 3)}))
    return findings


def _finding(chapter: dict, severity: str, code: str,
             message: str, detail: dict = None) -> Finding:
    return Finding(
        chapter_index=chapter["chapter_index"],
        chapter_id=chapter["id"],
        severity=severity,
        code=code,
        message=message,
        detail=detail or {},
    )


# ── Orchestration ──────────────────────────────────────────────────────────────

def audit_project(
    sm: StateManager,
    project_id: int,
    cfg: AuditConfig = None,
    chapter_range: "tuple[int,int] | None" = None,
) -> AuditReport:
    """
    Run all checks over a project and return an AuditReport.

    Read-only: opens no writes, mutates nothing. Raises ValueError for an
    unknown project_id.
    """
    cfg = cfg or AuditConfig()
    chapters = sm.get_all_chapters(project_id)
    if not chapters:
        raise ValueError(f"No chapters for project_id={project_id} "
                         "(unknown or unseeded project).")
    if chapter_range:
        lo, hi = chapter_range
        chapters = [c for c in chapters if lo <= c["chapter_index"] <= hi]

    voice_map  = sm.get_voice_map()
    ffprobe_ok = _ffprobe_available()
    findings: list[Finding] = []

    for ch in chapters:
        status = ch["status"]
        lines  = sm.get_lines_for_chapter(ch["id"])

        if status == "diarized":
            findings += _check_preflight(ch, lines, voice_map)

        if status == "error":
            findings.append(_finding(
                ch, "high", "chapter_error",
                f"chapter is in error state: {ch.get('error_message') or '?'}",
                {"error_message": ch.get("error_message")}))

        if status in _SYNTH_DONE_STATUSES:
            findings += _check_failed_lines(ch, lines)
            findings += _check_completion(ch, lines, cfg)
            findings += _check_empty_text(ch, lines)
            findings += _check_speaker_collapse(ch, lines, cfg)

        if status == "complete":
            findings += _check_mp3(ch, lines, cfg, ffprobe_ok)

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.chapter_index))

    by_severity: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_code[f.code] = by_code.get(f.code, 0) + 1

    notes = []
    if not ffprobe_ok:
        notes.append("ffprobe unavailable — duration_anomaly check skipped.")

    summary = {
        "project_id": project_id,
        "chapters_audited": len(chapters),
        "total_findings": len(findings),
        "by_severity": by_severity,
        "by_code": by_code,
        "notes": notes,
    }
    return AuditReport(
        findings=findings,
        summary=summary,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
