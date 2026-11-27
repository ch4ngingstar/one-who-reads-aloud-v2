"""
Seed the original demo scene into the pipeline DB, already labelled by hand.

To seed AND record it with the directed cast, use:

    python scripts/render_demo.py

This module only holds the scene and the seeding helpers. Run on its own it seeds
the lines (status 'diarized') without recording them:

    python scripts/seed_demo.py [--force]

Output of render_demo.py: data/output/demo_scene/*.mp3
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from state_manager import StateManager

_DB_DEFAULT = str(Path(__file__).resolve().parent.parent / "src" / "data" / "pipeline.db")

_PROJECT_NAME = "demo_scene"
_SOURCE_EPUB  = "demo_scene.epub"   # placeholder — orchestrator checks by stem, never opens it

# An original scene written for this project (no novel text). Speakers and emotions are
# set by hand; emotions stay within the delivery cues that won blind votes.
_LINES = [
    {"line_index": 0, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "The fog came up off the river an hour before dusk, and by nightfall the old bridge was the only thing left in the world."},
    {"line_index": 1, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Sunny sat on the parapet with his back to the drop, watching the far bank through the eyes of his shadow."},
    {"line_index": 2, "speaker": "Sunny", "emotion": "neutral", "kind": "thought",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Nothing on the road. Nothing in the trees. Which, around here, usually means something very patient."},
    {"line_index": 3, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Behind him, Effie was digging through the supply packs with the focus of a woman on a sacred quest."},
    {"line_index": 4, "speaker": "Effie", "emotion": "laughing", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Who ate the last of the dried fruit? I'm not angry. I just want to know who I'm going to be angry at."},
    {"line_index": 5, "speaker": "Kai", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "It was you, Effie. Yesterday. You said it was for morale."},
    {"line_index": 6, "speaker": "Effie", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Well. Morale was very high yesterday."},
    {"line_index": 7, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Nephis didn't look up from the fire. She was turning a small silver coin across her knuckles, the way she did when she was counting something only she could see."},
    {"line_index": 8, "speaker": "Nephis", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "We cross at first light. Not before. Sunny, how far does the bridge go?"},
    {"line_index": 9, "speaker": "Sunny", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Farther than it should. I sent my shadow halfway across, and it still couldn't see the other end."},
    {"line_index": 10, "speaker": "Sunny", "emotion": "neutral", "kind": "thought",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Which is a lovely thing to learn about a bridge you're about to sleep on."},
    {"line_index": 11, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Cassie had been silent all evening. Now she tilted her head, as if listening to a song no one else could hear."},
    {"line_index": 12, "speaker": "Cassie", "emotion": "whispers", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Don't light another torch. Something on the water is following the light."},
    {"line_index": 13, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "For a moment, nobody moved. Then Jet smiled, slow and pleased, and rested her chin on the shaft of her scythe."},
    {"line_index": 14, "speaker": "Jet", "emotion": "cold", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Good. I was getting bored."},
    {"line_index": 15, "speaker": "Kai", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "If it's following the light, I could lead it away. It only needs to hear something worth chasing."},
    {"line_index": 16, "speaker": "Nephis", "emotion": "neutral", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "No. We stay together. Cassie, how many?"},
    {"line_index": 17, "speaker": "Cassie", "emotion": "sad", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Just one. But it's very large, and very hungry, and it has been waiting under this bridge for a long, long time."},
    {"line_index": 18, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Somewhere below them, the river stopped making any sound at all."},
    {"line_index": 19, "speaker": "Sunny", "emotion": "neutral", "kind": "thought",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Of course it has."},
    {"line_index": 20, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Then a voice rang out inside each of their minds, calm and indifferent, as it always was."},
    {"line_index": 21, "speaker": "The Nightmare Spell", "emotion": "neutral", "kind": "system",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Beware. Something ancient has taken notice of you."},
    {"line_index": 22, "speaker": "Sunny", "emotion": "commanding", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Everyone up. Back to back. Effie, take the left."},
    {"line_index": 23, "speaker": "Effie", "emotion": "laughing", "kind": "dialogue",
     "attribution": {"method": "manual", "cue_indices": []},
     "text": "Finally. Something to do."},
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
    print(f"[seed_demo] Project '{_PROJECT_NAME}' (id {project_id}), chapter id {chapter_id}.")
    print("[seed_demo] Record it with the directed cast:  python scripts/render_demo.py")


if __name__ == "__main__":
    main()
