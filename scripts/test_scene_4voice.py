"""
Four-voice scene test: Narrator, Sunny, Rain, Nephis (~3 minutes).

Seeds a self-contained dialogue scene (already labelled speaker + emotion) and
runs the real TTS + assembly path, so you can judge the new Nephis (A2) and Rain
(ElevenLabs) clips alongside Sunny and the Narrator — and hear whether the
loudness matching holds across speakers.

Usage (from repo root):
    python scripts/test_scene_4voice.py

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

_PROJECT_NAME = "scene_4voice"
_EPUB_STEM    = f"{_PROJECT_NAME}.epub"

# "The Drowned Vault" — Nephis leads Sunny and Rain through a flooded ruin while
# something circles them in the dark. ~32 lines across 4 voices, varied emotion.
_SCRIPT = [
    ("Narrator", "neutral",    "The water came up to their knees, black and motionless, swallowing the light of the single torch Rain carried above her head."),
    ("Narrator", "neutral",    "The vault had been a temple once. Now its drowned pillars leaned at broken angles, and something vast had carved long grooves into the stone of the far wall."),
    ("Nephis",   "commanding", "Stay close, and keep to the center of the hall. The edges are where it will come from."),
    ("Narrator", "neutral",    "Nephis moved first, her blade low and steady, the surface of the water barely stirring around her."),
    ("Sunny",    "sarcastic",  "A flooded tomb with claw marks the size of a door. Truly, you take me to the most charming places."),
    ("Narrator", "neutral",    "Sunny let his shadow spread out beneath the water, feeling for the shape of the room."),
    ("Rain",     "neutral",    "There's a current here. Something is moving the water from deeper in — that way, past the second arch."),
    ("Nephis",   "cold",       "Then that is where we are going. Whatever it guards is the reason we came."),
    ("Narrator", "neutral",    "Rain's torch guttered as a slow ripple rolled past their legs, moving against the current."),
    ("Rain",     "frightened", "That wasn't us. Something just moved — it came toward us and then it stopped."),
    ("Sunny",    "cold",       "It's circling. It has been since we stepped inside. It's deciding whether we are worth the effort."),
    ("Narrator", "neutral",    "For a long moment none of them moved, and the only sound was the water lapping against the broken pillars."),
    ("Nephis",   "neutral",    "Sunny. Can you see it through your shadow? I need to know how large it is before it commits."),
    ("Sunny",    "confused",   "That's the strange part. I can feel the water it displaces, but the thing itself — there's nothing there. Like a hole shaped like a beast."),
    ("Narrator", "frightened", "The torchlight bent. Something rose from the water without breaking its surface, tall and silent and wrong."),
    ("Rain",     "pleading",   "Please, we should go back. Whatever this is, it isn't worth dying in the dark for."),
    ("Nephis",   "commanding", "No. Hold your ground. If we run, it takes us from behind, one at a time. Together, it cannot."),
    ("Narrator", "neutral",    "Nephis raised her blade, and a thin line of light ran along its edge, the only brightness in the whole drowned hall."),
    ("Sunny",    "cold",       "She's right. Backs together. Rain, keep the torch high — it doesn't like the light."),
    ("Narrator", "neutral",    "They formed a tight circle, the water churning now as the shape drew its slow, deliberate orbit closer."),
    ("Rain",     "sad",        "I always thought it would be loud, at the end. Not this. Not so quiet you can hear yourself breathing."),
    ("Nephis",   "cold",       "It will not be the end. Not tonight, and not to this. Steady your hand."),
    ("Narrator", "excited",    "And then Sunny saw it — the flaw in the thing, a seam of pale light buried where its heart should be, pulsing in time with the current."),
    ("Sunny",    "neutral",    "There. Under the ribs, where the water glows. That's what's keeping it here. Break that and it goes back to being nothing."),
    ("Nephis",   "commanding", "Then we break it. On my mark — Rain, the torch into its face; Sunny, the shadow under its feet."),
    ("Rain",     "whispers",   "On your mark. I'm ready. I'm right here."),
    ("Narrator", "neutral",    "The creature lunged, faster than its slow circling had promised, a wall of black water rising with it."),
    ("Sunny",    "angry",      "Now! Hit it now, before it closes the distance!"),
    ("Narrator", "neutral",    "Light and shadow struck at once, and the pale seam at the creature's heart cracked like ice under a hammer."),
    ("Nephis",   "cold",       "It's done. Lower the torch before you blind us all. We move on, before another one wakes."),
    ("Rain",     "neutral",    "It's gone. The water's going still again. I can feel the current settling."),
    ("Narrator", "neutral",    "They waded on through the dark, toward the second arch and whatever waited beyond it, and the drowned vault closed its silence behind them."),
]

_LINES = [
    {"line_index": i, "speaker": s, "emotion": e, "text": t}
    for i, (s, e, t) in enumerate(_SCRIPT)
]


def _upsert_project(sm):
    with sm._conn() as conn:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)).fetchone()
        if row:
            return row["id"]
        conn.execute("INSERT INTO projects (name, source_epub, total_chapters) VALUES (?, ?, 1)",
                     (_PROJECT_NAME, _EPUB_STEM))
        return conn.execute("SELECT id FROM projects WHERE name = ?", (_PROJECT_NAME,)).fetchone()["id"]


def _upsert_chapter(sm, project_id):
    with sm._conn() as conn:
        row = conn.execute("SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0", (project_id,)).fetchone()
        if row:
            return row["id"]
        conn.execute("""INSERT INTO chapters (project_id, chapter_index, title, total_chunks, status)
                        VALUES (?, 0, 'Four-Voice Scene', 0, 'pending')""", (project_id,))
        return conn.execute("SELECT id FROM chapters WHERE project_id = ? AND chapter_index = 0", (project_id,)).fetchone()["id"]


def _on_progress(event):
    if event.get("type") in ("model_load", "tts_progress", "stage_done", "chapter_done", "pipeline_done"):
        print(f"[{time.strftime('%H:%M:%S')}] {event}", flush=True)


def main():
    sm = StateManager(DB_PATH)
    for spk in ("Narrator", "Sunny", "Rain", "Nephis"):
        if spk not in sm.get_voice_map():
            print(f"[scene] WARNING: '{spk}' not registered — will use default voice.")
    project_id = _upsert_project(sm)
    chapter_id = _upsert_chapter(sm, project_id)
    sm.save_diarized_lines(chapter_id, _LINES)
    print(f"[scene] Seeded {len(_LINES)} lines (Narrator/Sunny/Rain/Nephis) "
          f"-> project_id={project_id}, chapter_id={chapter_id}.")

    config = PipelineConfig(
        epub_path      = _EPUB_STEM,
        llm_model_path = "unused.gguf",
        tts_model_dir  = TTS_MODEL_DIR,
        db_path        = DB_PATH,
        audio_wav_dir  = "data/audio",
        audio_mp3_dir  = "data/output",
        chapter_range  = (0, 0),
    )
    print("[scene] Synthesising ~3 minutes of audio — a few minutes on the GPU...")
    results = PipelineOrchestrator(config, progress_callback=_on_progress).run()
    print(f"[scene] Done: {results}", flush=True)

    out = SRC / "data" / "output" / f"ch_{chapter_id:04d}.mp3"
    if out.exists():
        print("\n" + "=" * 55)
        print(f"  SCENE READY:  {out}")
        print(f"  ({out.stat().st_size/1_000_000:.2f} MB)")
        print("=" * 55)
    else:
        print(f"[scene] Output not found at {out} — check the log above.")


if __name__ == "__main__":
    main()
