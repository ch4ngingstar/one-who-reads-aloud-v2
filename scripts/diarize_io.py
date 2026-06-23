"""
External diarization CLI: export segments, import labels, optional cloud format.

Decouples the slow local Qwen3-14B diarization stage: export a chapter's
deterministic segments, format speaker+emotion labels anywhere (cloud LLM /
hand), import them back. Text is never trusted from the external source.

Run from repo root:
    python scripts/diarize_io.py export --project "Shadow Slave" --range 258 260
    python scripts/diarize_io.py format-cloud --in data/diar_export
    python scripts/diarize_io.py import --project "Shadow Slave" --in data/diar_export
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager       # noqa: E402
import diarization_io as dio                  # noqa: E402

DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"


def _ch_name(chapter_id: int) -> str:
    return f"ch_{chapter_id:04d}"


def _resolve_project(sm: StateManager, name: str) -> int:
    proj = sm.get_project(name)
    if proj is None:
        sys.exit(f"error: no project named {name!r}")
    return proj["id"]


def _chapters_in_range(sm, project_id, rng):
    chapters = sm.get_all_chapters(project_id)
    if rng:
        lo, hi = rng
        chapters = [c for c in chapters if lo <= c["chapter_index"] <= hi]
    return chapters


def cmd_export(args):
    sm = StateManager(db_path=args.db)
    pid = _resolve_project(sm, args.project)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "system_prompt.txt").write_text(
        dio.build_system_prompt_text(), encoding="utf-8")

    n = 0
    for ch in _chapters_in_range(sm, pid, args.range):
        dest = out / f"{_ch_name(ch['id'])}.segments.json"
        if dest.exists() and not args.force:
            continue
        payload = dio.build_export(sm, ch["id"])
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        n += 1
        print(f"exported {dest.name} ({len(payload['segments'])} segments)")
    print(f"\n{n} chapter(s) exported to {out}")


def cmd_import(args):
    sm = StateManager(db_path=args.db)
    _resolve_project(sm, args.project)  # validate project exists
    src = Path(args.in_dir)
    if not src.is_dir():
        sys.exit(f"error: {src} is not a directory")

    ok = bad = 0
    for label_file in sorted(src.glob("ch_*.labels.json")):
        chapter_id = int(label_file.name[len("ch_"):].split(".")[0])
        payload = json.loads(label_file.read_text(encoding="utf-8"))
        try:
            n = dio.import_labels(sm, chapter_id, payload, force=args.force)
            print(f"  OK   {label_file.name} -> {n} lines (diarized)")
            ok += 1
        except dio.ImportRejected as e:
            print(f"  SKIP {label_file.name}: {e}")
            bad += 1
    print(f"\n{ok} imported, {bad} rejected")
    sys.exit(1 if bad else 0)


def cmd_format_cloud(args):
    """Optional: call Anthropic to produce labels from exported segments."""
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("error: set ANTHROPIC_API_KEY to use format-cloud")

    src = Path(args.in_dir)
    done = 0
    for seg_file in sorted(src.glob("ch_*.segments.json")):
        chapter_id = int(seg_file.name[len("ch_"):].split(".")[0])
        out_file = src / f"ch_{chapter_id:04d}.labels.json"
        if out_file.exists() and not args.force:
            continue
        payload = json.loads(seg_file.read_text(encoding="utf-8"))
        try:
            labels = dio.format_labels_via_claude(
                payload, api_key=api_key, model=args.model)
        except dio.ImportRejected as e:
            sys.exit(f"error: {e}")
        labels["chapter_id"] = chapter_id
        out_file.write_text(json.dumps(labels, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        done += 1
        print(f"formatted {out_file.name}")
    print(f"\n{done} chapter(s) formatted")


def main():
    p = argparse.ArgumentParser(description="External diarization import/export")
    p.add_argument("--db", default=str(DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export")
    pe.add_argument("--project", required=True)
    pe.add_argument("--range", nargs=2, type=int, metavar=("LO", "HI"))
    pe.add_argument("--out", default="data/diar_export")
    pe.add_argument("--force", action="store_true")
    pe.set_defaults(func=cmd_export)

    pi = sub.add_parser("import")
    pi.add_argument("--project", required=True)
    pi.add_argument("--in", dest="in_dir", default="data/diar_export")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_import)

    pc = sub.add_parser("format-cloud")
    pc.add_argument("--in", dest="in_dir", default="data/diar_export")
    pc.add_argument("--model", default="claude-opus-4-8")
    pc.add_argument("--force", action="store_true")
    pc.set_defaults(func=cmd_format_cloud)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
