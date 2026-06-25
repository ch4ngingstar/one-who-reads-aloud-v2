"""
One-shot voice-quality smoke test.

Seeds a short, pre-diarized scene into the pipeline DB and runs it through the
REAL TTS + assembly path (IndexTTS2 → FFmpeg concat), so you can listen to the
output and judge voice quality after the loudnorm fix.

It is fully self-contained:
  * seeds a 'voice_test' project + one chapter, already labelled (speaker +
    emotion per line) → the orchestrator skips EPUB parsing and the LLM and
    goes straight to synthesis,
  * loads IndexTTS2 once, synthesises every line, assembles a chapter MP3,
  * prints the output path.

Usage (from repo root):
    python scripts/test_voice_quality.py

Output: src/data/output/ch_<id>.mp3
"""

import os
import sys
import time
from pathlib import Path

# Run from src/ so the relative DB / audio / output paths resolve exactly like
# the production pipeline (and so the registered voice clips are found).
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
os.chdir(SRC)

from state_manager import StateManager          # noqa: E402
from orchestrator import PipelineOrchestrator, PipelineConfig  # noqa: E402

ROOT          = SRC.parent
TTS_MODEL_DIR = str(ROOT / "index-tts" / "checkpoints")
DB_PATH       = "data/pipeline.db"               # relative to src/ (cwd)

# Project name MUST equal the epub_path stem — the orchestrator matches an
# existing project by stem and then resumes WITHOUT parsing the epub or touching
# the LLM. The .epub file is never opened for an already-seeded project.
_PROJECT_NAME = "voice_test"
_EPUB_STEM    = f"{_PROJECT_NAME}.epub"

# A fresh scene (not the README demo) — varied speakers and emotions so the clip
# stresses several cloned voices, not just one. Every speaker here is registered
# in the voice map; every emotion is a key in INDEXTTS2_EMOTION_VECTORS.
_LINES = [
    {"line_index": 0, "speaker": "Narrator", "emotion": "neutral",
     "text": "The lift cage rattled down into the dark, and the air grew colder with every floor."},
    {"line_index": 1, "speaker": "Sunny", "emotion": "sarcastic",
     "text": "A bottomless pit that smells like wet iron. Wonderful. I always wanted to die somewhere memorable."},
    {"line_index": 2, "speaker": "Narrator", "emotion": "neutral",
     "text": "Nephis studied the runes burned into the cage wall, her expression unreadable."},
    {"line_index": 3, "speaker": "Nephis", "emotion": "cold",
     "text": "Save your breath. Whatever made these markings did not do it to frighten us."},
    {"line_index": 4, "speaker": "Effie", "emotion": "excited",
     "text": "Ooh, ancient and ominous! See, this is exactly the kind of trouble I signed up for."},
    {"line_index": 5, "speaker": "Narrator", "emotion": "neutral",
     "text": "Cassie pressed herself against the back of the cage, her voice barely a whisper."},
    {"line_index": 6, "speaker": "Cassie", "emotion": "frightened",
     "text": "There is something breathing down there. I can feel it in my teeth. Please, let's not do this."},
    {"line_index": 7, "speaker": "Narrator", "emotion": "neutral",
     "text": "Kai checked the tension on his blade and spoke without looking up."},
    {"line_index": 8, "speaker": "Kai", "emotion": "commanding",
     "text": "Stay close, watch your footing, and do not touch the walls. We move on my mark."},
    {"line_index": 9, "speaker": "Narrator", "emotion": "neutral",
     "text": "The cage shuddered to a halt. Far below, in the absolute black, something vast began to stir."},
    {"line_index": 10, "speaker": "Sunny", "emotion": "neutral",
     "text": "Right. On your mark, then. Try not to enjoy this too much."},
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
            (_PROJECT_NAME, _EPUB_STEM),
        )
        return conn.execute(
            "SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)
        ).fetchone()["id"]


def _upsert_chapter(sm: StateManager, project_id: int) -> int:
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0",
            (project_id,),
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            """INSERT INTO chapters
                 (project_id, chapter_index, title, total_chunks, status)
               VALUES (?, 0, 'Voice Quality Test', 0, 'pending')""",
            (project_id,),
        )
        return conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0",
            (project_id,),
        ).fetchone()["id"]


def _on_progress(event):
    t = event.get("type", "")
    if t in ("pipeline_start", "model_load", "chapter_start", "stage_start",
             "stage_done", "tts_progress", "chapter_done", "chapter_error",
             "vram_barrier", "pipeline_done", "pipeline_stopped"):
        print(f"[{time.strftime('%H:%M:%S')}] {event}", flush=True)


def main():
    db = SRC / DB_PATH
    if not db.exists():
        print(f"[test] DB not found: {db}")
        print("[test] Start the backend once to initialise it, then retry.")
        sys.exit(1)

    sm = StateManager(DB_PATH)
    project_id = _upsert_project(sm)
    chapter_id = _upsert_chapter(sm, project_id)

    # Re-seed the lines every run and force status back to 'diarized' so the
    # orchestrator always re-synthesises (gives a clean before/after compare).
    sm.save_diarized_lines(chapter_id, _LINES)
    print(f"[test] Seeded {len(_LINES)} lines into '{_PROJECT_NAME}' "
          f"(project_id={project_id}, chapter_id={chapter_id}, status=diarized).")

    config = PipelineConfig(
        epub_path      = _EPUB_STEM,     # stem matches the seeded project → no parse, no LLM
        llm_model_path = "unused.gguf",  # never opened for a diarized chapter
        tts_model_dir  = TTS_MODEL_DIR,
        db_path        = DB_PATH,
        audio_wav_dir  = "data/audio",
        audio_mp3_dir  = "data/output",
        chapter_range  = (0, 0),
    )

    print("[test] Loading IndexTTS2 and synthesising — this takes a few minutes...")
    orch    = PipelineOrchestrator(config, progress_callback=_on_progress)
    results = orch.run()
    print(f"[test] Done: {results}", flush=True)

    out = SRC / "data" / "output" / f"ch_{chapter_id:04d}.mp3"
    if out.exists():
        size_mb = out.stat().st_size / 1_000_000
        print("\n" + "=" * 55)
        print("  LISTEN HERE:")
        print(f"  {out}")
        print(f"  ({size_mb:.2f} MB)")
        print("=" * 55)
    else:
        print(f"[test] Expected output not found at {out} — check the log above.")


if __name__ == "__main__":
    main()
