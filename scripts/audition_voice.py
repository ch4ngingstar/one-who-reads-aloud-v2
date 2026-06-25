"""
Audition a single speaker's voice across a range of emotions.

Seeds a short scene where EVERY line is spoken by one chosen speaker, each with a
different emotion tag, then runs the real TTS + assembly path so you can judge
the cloned voice's timbre and emotional range in one clip.

Usage (from repo root):
    python scripts/audition_voice.py                # auditions "Nephis"
    python scripts/audition_voice.py "Sunny"        # any registered speaker

Output: src/data/output/ch_<id>.mp3
"""

import os
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
os.chdir(SRC)

from state_manager import StateManager                         # noqa: E402
from orchestrator import PipelineOrchestrator, PipelineConfig  # noqa: E402

ROOT          = SRC.parent
TTS_MODEL_DIR = str(ROOT / "index-tts" / "checkpoints")
DB_PATH       = "data/pipeline.db"

SPEAKER       = sys.argv[1] if len(sys.argv) > 1 else "Nephis"
_PROJECT_NAME = "voice_audition"
_EPUB_STEM    = f"{_PROJECT_NAME}.epub"

# Emotion-spanning lines, all spoken by the audition speaker. Text is written in
# a serious first-person register that suits most characters while still
# exercising each emotion tag (every tag here is in INDEXTTS2_EMOTION_VECTORS).
_SCRIPT = [
    ("neutral",    "We make camp here for the night. At first light, we descend into the lower gates."),
    ("cold",       "Save your breath. Whatever made these markings did not do it to frighten us."),
    ("commanding", "Hold the line. No one takes a single step back. Do you understand me?"),
    ("sad",        "I have buried too many of the people I swore to protect. I will not bury more."),
    ("whispers",   "Stay quiet. Something is moving out there, just beyond the edge of the light."),
    ("angry",      "You had one task, and you failed it. Do not make me say it twice."),
    ("excited",    "There — do you see it? The path is finally open. We move, now."),
]

_LINES = [
    {"line_index": i, "speaker": SPEAKER, "emotion": emo, "text": text}
    for i, (emo, text) in enumerate(_SCRIPT)
]


def _upsert_project(sm: StateManager) -> int:
    with sm._conn() as conn:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)).fetchone()
        if row:
            return row["id"]
        conn.execute(
            "INSERT INTO projects (name, source_epub, total_chapters) VALUES (?, ?, 1)",
            (_PROJECT_NAME, _EPUB_STEM),
        )
        return conn.execute("SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)).fetchone()["id"]


def _upsert_chapter(sm: StateManager, project_id: int) -> int:
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0", (project_id,)
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            """INSERT INTO chapters (project_id, chapter_index, title, total_chunks, status)
               VALUES (?, 0, 'Voice Audition', 0, 'pending')""",
            (project_id,),
        )
        return conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0", (project_id,)
        ).fetchone()["id"]


def _on_progress(event):
    if event.get("type") in ("model_load", "tts_progress", "stage_done",
                             "chapter_done", "chapter_error", "pipeline_done"):
        print(f"[{time.strftime('%H:%M:%S')}] {event}", flush=True)


def main():
    db = SRC / DB_PATH
    if not db.exists():
        print(f"[audition] DB not found: {db}")
        sys.exit(1)

    sm = StateManager(DB_PATH)

    if SPEAKER not in sm.get_voice_map():
        print(f"[audition] WARNING: '{SPEAKER}' is not in the voice map — it will "
              f"fall back to the default voice. Registered speakers:")
        print("  " + ", ".join(sorted(sm.get_voice_map().keys())))

    project_id = _upsert_project(sm)
    chapter_id = _upsert_chapter(sm, project_id)
    sm.save_diarized_lines(chapter_id, _LINES)
    print(f"[audition] Speaker '{SPEAKER}' — {len(_LINES)} lines "
          f"({', '.join(e for e, _ in _SCRIPT)}).")

    config = PipelineConfig(
        epub_path      = _EPUB_STEM,
        llm_model_path = "unused.gguf",
        tts_model_dir  = TTS_MODEL_DIR,
        db_path        = DB_PATH,
        audio_wav_dir  = "data/audio",
        audio_mp3_dir  = "data/output",
        chapter_range  = (0, 0),
    )

    print("[audition] Synthesising — a couple of minutes...")
    results = PipelineOrchestrator(config, progress_callback=_on_progress).run()
    print(f"[audition] Done: {results}", flush=True)

    out = SRC / "data" / "output" / f"ch_{chapter_id:04d}.mp3"
    if out.exists():
        print("\n" + "=" * 55)
        print(f"  AUDITION READY ({SPEAKER}):")
        print(f"  {out}")
        print(f"  ({out.stat().st_size/1_000_000:.2f} MB)")
        print("=" * 55)
    else:
        print(f"[audition] Output not found at {out} — check the log above.")


if __name__ == "__main__":
    main()
