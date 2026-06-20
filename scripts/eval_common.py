"""
Shared helpers for the TTS/diarization evaluation harness (scripts/eval_*.py).

Read-only with respect to pipeline state — these utilities only read the DB and
the on-disk WAVs/MP3s. Nothing here mutates `pipeline.db` or audio files.

All eval scripts share:
  - src/ path bootstrap + repo-root anchoring (so `from state_manager import ...`)
  - project selection (mirrors scripts/qa_audit.py semantics)
  - per-line WAV resolution (DB audio_path first, then conventional layout)
  - CSV / JSON / Markdown writers for reports
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# pipeline.db lives under src/data when the pipeline is run from src/ (see
# scripts/run_chapters.py which chdir's into src/). qa_audit.py uses the same.
DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"

# Per-line WAVs and chapter MP3s. The pipeline writes them relative to src/
# (audio_wav_dir="data/audio"), but _resolve_stored_path checks both roots, so
# these are only fallbacks when the DB has no audio_path recorded.
DEFAULT_AUDIO_ROOT = ROOT / "src" / "data" / "audio"
DEFAULT_OUTPUT_ROOT = ROOT / "src" / "data" / "output"

# IndexTTS2 checkpoints (config.yaml + weights) — only needed by eval_emotion.py.
DEFAULT_MODEL_DIR = ROOT / "index-tts" / "checkpoints"

REPORTS_DIR = ROOT / "docs"


def pick_project(sm, name=None) -> int:
    """Resolve a project_id. If `name` is None and there is exactly one project,
    use it; otherwise require an explicit --project. Mirrors scripts/qa_audit.py."""
    if name:
        proj = sm.get_project(name)
        if not proj:
            print(f"[eval] Project '{name}' not found.", file=sys.stderr)
            sys.exit(2)
        return proj["id"]
    projects = sm.list_projects()
    if not projects:
        print("[eval] No projects in the database.", file=sys.stderr)
        sys.exit(2)
    if len(projects) > 1:
        names = ", ".join(p["name"] for p in projects)
        print(f"[eval] Multiple projects — pass --project. Available: {names}",
              file=sys.stderr)
        sys.exit(2)
    return projects[0]["id"]


def resolve_line_wav(line: dict, chapter_id: int,
                     audio_root: Path = DEFAULT_AUDIO_ROOT) -> "Path | None":
    """Locate the WAV for a diarized line.

    Prefers the DB-recorded audio_path (resolved against both repo roots), and
    falls back to the conventional ch_XXXX/line_XXXX.wav layout. Returns the Path
    if the file exists on disk, else None.
    """
    from state_manager import _resolve_stored_path

    stored = line.get("audio_path")
    if stored:
        p = _resolve_stored_path(stored)
        if p.exists():
            return p
    conventional = audio_root / f"ch_{chapter_id:04d}" / f"line_{line['line_index']:04d}.wav"
    return conventional if conventional.exists() else None


def line_wavs_for_chapter(sm, chapter_id: int,
                          audio_root: Path = DEFAULT_AUDIO_ROOT) -> list:
    """Return [(line_dict, Path|None), ...] for every line of a chapter,
    ordered by line_index."""
    lines = sm.get_lines_for_chapter(chapter_id)
    return [(ln, resolve_line_wav(ln, chapter_id, audio_root)) for ln in lines]


def chapter_id_for_index(sm, project_id: int, chapter_index: int) -> "int | None":
    """Map a human chapter_index to the internal chapter_id (DB primary key)."""
    for ch in sm.get_all_chapters(project_id):
        if ch["chapter_index"] == chapter_index:
            return ch["id"]
    return None


def resolve_chapter_ids(sm, project_id: int, chapters: "list[int] | None",
                        by_index: bool) -> list:
    """Normalise a CLI --chapter list into internal chapter_ids.

    If by_index, the values are human chapter_index numbers; otherwise they are
    raw chapter_ids. With no list, returns every chapter that has diarized lines.
    """
    if chapters:
        if by_index:
            out = []
            for ci in chapters:
                cid = chapter_id_for_index(sm, project_id, ci)
                if cid is None:
                    print(f"[eval] chapter_index {ci} not found.", file=sys.stderr)
                    sys.exit(2)
                out.append(cid)
            return out
        return list(chapters)
    # default: every chapter that has at least one line
    out = []
    for ch in sm.get_all_chapters(project_id):
        if sm.get_lines_for_chapter(ch["id"]):
            out.append(ch["id"])
    return out


# ── Writers ───────────────────────────────────────────────────────────────────

def write_csv(path: Path, rows: list, fieldnames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def append_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n")
