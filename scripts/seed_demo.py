"""
Seed a pre-diarized demo chapter into the pipeline DB.

Bypasses EPUB parsing and LLM diarization entirely — lines are already
labelled with speaker + emotion, so the pipeline picks them up at the
TTS stage directly.

Usage (from repo root):
    python scripts/seed_demo.py

Then start synthesis via the UI:
  - Project: demo_scene
  - Chapter range: 0 – 0  (index, not ID)

Or via the API directly:
  POST /api/pipeline/start
  {
    "project_name": "demo_scene",
    "llm_model_path": "<your model path>",
    "tts_model_dir": "<your checkpoints dir>",
    "chapter_range": [0, 0]
  }

The orchestrator will find the project in the DB, skip EPUB parsing and
diarization (chapter is already 'diarized'), and run TTS + assemble only.
Output: data/output/ch_<id>.mp3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from state_manager import StateManager

_DB_DEFAULT = str(Path(__file__).resolve().parent.parent / "src" / "data" / "pipeline.db")

_PROJECT_NAME = "demo_scene"
_SOURCE_EPUB  = "demo_scene.epub"   # placeholder — orchestrator checks by stem, never opens it

_LINES = [
    {
        "line_index": 0,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text": (
            "The waystation at the edge of the Pale Meridian had no walls — "
            "just black stone pillars beneath a sky that flickered like a dying flame."
        ),
    },
    {
        "line_index": 1,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Lord Valor spread a map across the ruins of a table.",
    },
    {
        "line_index": 2,
        "speaker":    "Lord Valor",
        "emotion":    "commanding",
        "text": (
            "Three convergence points. Any one of them will kill an unprepared team "
            "in under a minute. We will not be unprepared."
        ),
    },
    {
        "line_index": 3,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Kai crouched at the northern pillar and pressed two fingers to the ground.",
    },
    {
        "line_index": 4,
        "speaker":    "Kai",
        "emotion":    "neutral",
        "text": (
            "The resonance pattern is recent. Something large passed through here — "
            "twelve hours ago, maybe less."
        ),
    },
    {
        "line_index": 5,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Effie leaned forward, her eyes bright.",
    },
    {
        "line_index": 6,
        "speaker":    "Effie",
        "emotion":    "excited",
        "text":       "That's not ominous at all. I love it when missions start like this.",
    },
    {
        "line_index": 7,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Cassie spoke quietly from the edge of the group.",
    },
    {
        "line_index": 8,
        "speaker":    "Cassie",
        "emotion":    "pleading",
        "text":       "Are we sure we have to go in now? The readings could stabilize by morning.",
    },
    {
        "line_index": 9,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Nephis did not turn from the horizon.",
    },
    {
        "line_index": 10,
        "speaker":    "Nephis",
        "emotion":    "cold",
        "text":       "They won't. By morning the window closes and we lose the season.",
    },
    {
        "line_index": 11,
        "speaker":    "Narrator",
        "emotion":    "neutral",
        "text":       "Sunny turned a shard of black glass over in his fingers.",
    },
    {
        "line_index": 12,
        "speaker":    "Sunny",
        "emotion":    "sarcastic",
        "text": (
            "So we go in knowing there's something large already inside, "
            "three ways to die immediately, and no way out if things go wrong."
        ),
    },
    {
        "line_index": 13,
        "speaker":    "Narrator",
        "emotion":    "frightened",
        "text":       "A silence settled over the waystation like snow.",
    },
    {
        "line_index": 14,
        "speaker":    "Nephis",
        "emotion":    "commanding",
        "text":       "Yes. That is correct.",
    },
]


def _upsert_project(sm: StateManager) -> int:
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) VALUES (?, ?, 1)",
            (_PROJECT_NAME, _SOURCE_EPUB),
        )
        return conn.execute(
            "SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)
        ).fetchone()["id"]


def _upsert_chapter(sm: StateManager, project_id: int) -> tuple[int, bool]:
    """Returns (chapter_id, already_existed)."""
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT id, status FROM chapters WHERE project_id = ? AND chapter_index = 0",
            (project_id,),
        ).fetchone()
        if row:
            return row["id"], True
        conn.execute(
            """INSERT INTO chapters
                 (project_id, chapter_index, title, total_chunks, status)
               VALUES (?, 0, 'Demo Scene — One Who Reads Aloud', 0, 'pending')""",
            (project_id,),
        )
        return conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0",
            (project_id,),
        ).fetchone()["id"], False


def main():
    ap = argparse.ArgumentParser(description="Seed demo chapter into pipeline DB")
    ap.add_argument("--db", default=_DB_DEFAULT, help="Path to pipeline.db")
    ap.add_argument("--force", action="store_true",
                    help="Re-seed lines even if the chapter is already synthesised")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"[seed_demo] DB not found: {db}")
        print("[seed_demo] Run the backend at least once to initialise the DB, then retry.")
        sys.exit(1)

    sm = StateManager(str(db))

    project_id = _upsert_project(sm)
    print(f"[seed_demo] Project '{_PROJECT_NAME}' — id={project_id}")

    chapter_id, existed = _upsert_chapter(sm, project_id)
    if existed:
        with sm._conn() as conn:
            status = conn.execute(
                "SELECT status FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()["status"]
        if status in ("tts_done", "complete") and not args.force:
            print(f"[seed_demo] Chapter already at '{status}'. Nothing to do.")
            print("[seed_demo] Use --force to re-seed lines and reset to 'diarized'.")
            _print_instructions(project_id, chapter_id)
            return
        print(f"[seed_demo] Chapter found (id={chapter_id}, status={status}). Re-seeding lines.")
    else:
        print(f"[seed_demo] Chapter created (id={chapter_id}).")

    sm.save_diarized_lines(chapter_id, _LINES)
    print(f"[seed_demo] {len(_LINES)} lines seeded — chapter status set to 'diarized'.")
    _print_instructions(project_id, chapter_id)


def _print_instructions(project_id: int, chapter_id: int) -> None:
    print()
    print("=" * 55)
    print("  Ready for TTS + assembly")
    print("=" * 55)
    print(f"  Project name : {_PROJECT_NAME}")
    print(f"  Project id   : {project_id}")
    print(f"  Chapter id   : {chapter_id}  (chapter_index = 0)")
    print()
    print("  Start via the UI:")
    print(f"    Project = {_PROJECT_NAME}")
    print(f"    Chapter range = 0 to 0")
    print()
    print("  Or via POST /api/pipeline/start:")
    print('  {')
    print(f'    "project_name":   "{_PROJECT_NAME}",')
    print('    "llm_model_path": "<path/to/model.gguf>",')
    print('    "tts_model_dir":  "<path/to/checkpoints>",')
    print('    "chapter_range":  [0, 0]')
    print('  }')
    print()
    print("  Output: data/output/ch_<chapter_id>.mp3")
    print("=" * 55)


if __name__ == "__main__":
    main()
