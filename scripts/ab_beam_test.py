"""
A/B beam-count test for IndexTTS2.

Re-synthesises specific lines of a chapter at num_beams=1 and places them next
to the already-generated num_beams=3 versions so the difference can be heard.

Run from the repo root (so 'index-tts/checkpoints' resolves):
    python scripts/ab_beam_test.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager          # noqa: E402
from tts_engine import TTSEngine, _normalize_text  # noqa: E402

DB_PATH   = ROOT / "src" / "data" / "pipeline.db"
MODEL_DIR = ROOT / "index-tts" / "checkpoints"
BEAM3_DIR = ROOT / "data" / "audio" / "ch_0258"   # existing num_beams=3 output
OUT_DIR   = ROOT / "data" / "ab_beams"

CHAPTER_ID = 258
LINES      = [6, 9]   # 6 = long neutral narration, 9 = excited narration


def synth_line(engine, line, voice_map):
    """Mirror TTSEngine.process_chapter's per-line synth, at the engine's cfg."""
    text                  = _normalize_text(line["text"])
    emo_vector, emo_alpha = engine._resolve_emotion(line["emotion"])
    emo_alpha            *= engine.cfg["emo_alpha_scale"]
    ref_path              = engine._resolve_ref_audio(
        line["speaker"], line["emotion"], voice_map
    )
    if ref_path is None:
        raise RuntimeError(f"No voice for speaker {line['speaker']!r}")

    segments = engine._split_long_line(text, engine.cfg["max_line_chars"])
    if len(segments) == 1:
        return engine._synthesize(segments[0], ref_path, emo_vector, emo_alpha)
    parts = [engine._synthesize(s, ref_path, emo_vector, emo_alpha) for s in segments]
    return engine._concat_wavs(parts)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sm = StateManager(str(DB_PATH))
    voice_map = sm.get_voice_map()

    # Pull the chosen lines from the DB.
    lines = {l["line_index"]: l for l in sm.get_pending_tts_lines(CHAPTER_ID)}
    # get_pending_tts_lines only returns not-yet-done lines; fall back to a direct read.
    import sqlite3
    db = sqlite3.connect(str(DB_PATH)); db.row_factory = sqlite3.Row
    wanted = {}
    for li in LINES:
        r = db.execute(
            "SELECT id, line_index, speaker, text, emotion "
            "FROM lines WHERE chapter_id=? AND line_index=?",
            (CHAPTER_ID, li),
        ).fetchone()
        wanted[li] = dict(r)

    print(f"[ab] Loading IndexTTS2 with num_beams=1 from {MODEL_DIR} ...")
    with TTSEngine(sm, OUT_DIR, model_dir=str(MODEL_DIR), cfg={"num_beams": 1}) as engine:
        for li in LINES:
            line = wanted[li]
            print(f"[ab] Synthesising line {li} "
                  f"[{line['speaker']}/{line['emotion']}] at num_beams=1 ...")
            wav = synth_line(engine, line, voice_map)
            out = OUT_DIR / f"beam1_line{li:04d}.wav"
            out.write_bytes(wav)
            print(f"[ab]   -> {out}")

            # Copy the existing num_beams=3 version next to it for comparison.
            src3 = BEAM3_DIR / f"line_{li:04d}.wav"
            if src3.exists():
                dst3 = OUT_DIR / f"beam3_line{li:04d}.wav"
                shutil.copyfile(src3, dst3)
                print(f"[ab]   (beam3 reference copied -> {dst3})")
            else:
                print(f"[ab]   (no beam3 reference at {src3})")

    print(f"\n[ab] Done. Compare files in: {OUT_DIR}")


if __name__ == "__main__":
    main()
