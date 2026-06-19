"""Correctness audit CLI — flag suspect chapters/lines before/after a run.

Read-only: scans the pipeline DB (and finished MP3s) and reports problems. It
NEVER mutates the DB or files, so it is safe to run mid-backlog. Exit code is 0
when clean and 1 when any finding is present, so it can gate a shell script.

Run from repo root:
    python scripts/qa_audit.py                       # default DB + project
    python scripts/qa_audit.py --project shadow_slave
    python scripts/qa_audit.py --range 0 50          # only chapters 0..50
    python scripts/qa_audit.py --severity high       # only high-severity
    python scripts/qa_audit.py --json                # machine-readable output
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager
from qa_audit import audit_project, AuditConfig, SEVERITY_ORDER

DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"


def _pick_project(sm: StateManager, name: "str | None") -> int:
    if name:
        proj = sm.get_project(name)
        if not proj:
            print(f"[qa] Project '{name}' not found.", file=sys.stderr)
            sys.exit(2)
        return proj["id"]
    projects = sm.list_projects()
    if not projects:
        print("[qa] No projects in the database.", file=sys.stderr)
        sys.exit(2)
    if len(projects) > 1:
        names = ", ".join(p["name"] for p in projects)
        print(f"[qa] Multiple projects — pass --project. Available: {names}",
              file=sys.stderr)
        sys.exit(2)
    return projects[0]["id"]


def _print_human(report, min_severity: "str | None") -> None:
    order = SEVERITY_ORDER
    floor = order.get(min_severity, 99) if min_severity else 99
    shown = [f for f in report.findings
             if not min_severity or order.get(f.severity, 9) <= floor]

    s = report.summary
    print(f"\n{'=' * 64}")
    print(f"Correctness audit — project_id={s['project_id']}, "
          f"{s['chapters_audited']} chapter(s) audited")
    print(f"{'=' * 64}")
    for note in s.get("notes", []):
        print(f"  note: {note}")

    if not shown:
        print("\n  ✓ No findings — nothing flagged.\n")
        return

    print()
    last_ch = None
    for f in shown:
        if f.chapter_index != last_ch:
            print(f"  Chapter {f.chapter_index:>4} (id={f.chapter_id})")
            last_ch = f.chapter_index
        print(f"    [{f.severity:<6}] {f.code:<22} {f.message}")

    print(f"\n  Totals: {s['total_findings']} finding(s) — "
          + ", ".join(f"{k}={v}" for k, v in sorted(
              s['by_severity'].items(), key=lambda kv: order.get(kv[0], 9)))
          + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only correctness audit.")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to pipeline.db")
    ap.add_argument("--project", default=None, help="project name (default: the only one)")
    ap.add_argument("--range", nargs=2, type=int, metavar=("START", "END"),
                    default=None, help="inclusive chapter_index range")
    ap.add_argument("--severity", choices=["high", "medium", "low"], default=None,
                    help="only show findings at this severity or higher")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    sm = StateManager(args.db)
    project_id = _pick_project(sm, args.project)
    rng = tuple(args.range) if args.range else None
    report = audit_project(sm, project_id, AuditConfig(), chapter_range=rng)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report, args.severity)

    sys.exit(1 if report.findings else 0)


if __name__ == "__main__":
    main()
