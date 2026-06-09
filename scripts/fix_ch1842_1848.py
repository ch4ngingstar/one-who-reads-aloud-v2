"""
Fix speaker misattributions in chapters 1842 (id=255) and 1848 (id=261).

Issues found:
  ch255 (1842):
    - Line 8:  duplicate of Nephis's dialogue assigned to Sunny -> mark failed (skip)
    - Line 9:  Sunny's dialogue assigned to Narrator -> fix to Sunny
    - Line 10: Narrator text assigned to Sunny -> fix to Narrator
    - Line 13: Narrator description assigned to Sunny -> fix to Narrator
    - Line 14: Narrator description assigned to Sunny -> fix to Narrator
    - Line 16: Narrator description assigned to Sunny -> fix to Narrator
    - Line 27: Sunny's dialogue assigned to Narrator -> fix to Sunny
    - Line 36: Narrator action assigned to Sunny -> fix to Narrator
    - Line 42: Narrator action assigned to Sunny -> fix to Narrator
    - Line 44: Narrator action assigned to Aiko -> fix to Narrator
    - Line 69: Narrator action assigned to Sunny -> fix to Narrator

  ch261 (1848):
    - Lines 1,3,5,7,9,11: 3rd-person narration assigned to Sunny -> fix to Narrator
    - Line 16: "Sunny shivered..." assigned to Sunny -> fix to Narrator
    - Line 29: "Down below, Sunny's avatar..." assigned to Sunny -> fix to Narrator
    - Line 40: "Sunny knew that..." assigned to Sunny -> fix to Narrator
    - Line 41: Sunny's inner sarcastic voice assigned to Narrator -> fix to Sunny
    - Line 42: Narrator narration assigned to Sunny -> fix to Narrator

After running:
  - Wrong WAV files are deleted
  - Lines are reset to 'pending'
  - Chapters are set to 'diarized' so next pipeline run re-synthesizes + re-assembles
"""

import sqlite3
from pathlib import Path

DB_PATH    = Path(__file__).parent.parent / "src" / "data" / "pipeline.db"
AUDIO_BASE = Path(__file__).parent.parent / "src" / "data" / "audio"


def fix(conn, chapter_id: int, line_index: int, speaker: str, emotion: str,
        *, mark_failed: bool = False) -> None:
    row = conn.execute(
        "SELECT id, audio_path, speaker, emotion FROM lines "
        "WHERE chapter_id=? AND line_index=?",
        (chapter_id, line_index),
    ).fetchone()

    if not row:
        print(f"  WARN: chapter={chapter_id} line={line_index} not found — skipped")
        return

    old_speaker = row["speaker"]
    old_emotion = row["emotion"]
    audio_path  = row["audio_path"]
    line_id     = row["id"]

    if mark_failed:
        conn.execute(
            "UPDATE lines SET status='failed', audio_path=NULL WHERE id=?",
            (line_id,),
        )
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                p.unlink()
        print(f"  SKIP  ch{chapter_id} line {line_index:02d}: "
              f"{old_speaker}({old_emotion}) -> marked failed (duplicate)")
        return

    conn.execute(
        "UPDATE lines SET speaker=?, emotion=?, status='pending', audio_path=NULL "
        "WHERE id=?",
        (speaker, emotion, line_id),
    )

    if audio_path:
        p = Path(audio_path)
        if p.exists():
            p.unlink()
            print(f"  FIX   ch{chapter_id} line {line_index:02d}: "
                  f"{old_speaker}({old_emotion}) -> {speaker}({emotion})  [WAV deleted]")
        else:
            print(f"  FIX   ch{chapter_id} line {line_index:02d}: "
                  f"{old_speaker}({old_emotion}) -> {speaker}({emotion})  [WAV missing]")
    else:
        print(f"  FIX   ch{chapter_id} line {line_index:02d}: "
              f"{old_speaker}({old_emotion}) -> {speaker}({emotion})")


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # ── Chapter 255 (1842) ────────────────────────────────────────────────────
    print("\nChapter 255 (1842: First Blood):")
    fix(conn, 255,  8, "Narrator", "neutral", mark_failed=True)   # duplicate line
    fix(conn, 255,  9, "Sunny",    "cold")                         # Sunny's dialogue
    fix(conn, 255, 10, "Narrator", "neutral")                      # action prose
    fix(conn, 255, 13, "Narrator", "neutral")                      # scene description
    fix(conn, 255, 14, "Narrator", "neutral")                      # scene description
    fix(conn, 255, 16, "Narrator", "neutral")                      # relationship description
    fix(conn, 255, 27, "Sunny",    "cold")                         # Sunny's dialogue reply
    fix(conn, 255, 36, "Narrator", "neutral")                      # action prose
    fix(conn, 255, 42, "Narrator", "neutral")                      # action prose
    fix(conn, 255, 44, "Narrator", "neutral")                      # Aiko action prose
    fix(conn, 255, 69, "Narrator", "neutral")                      # "Sunny's eyes narrowed"

    conn.execute(
        "UPDATE chapters SET status='diarized', updated_at=datetime('now') WHERE id=255"
    )
    print("  -> Chapter 255 reset to 'diarized'")

    # ── Chapter 261 (1848) ────────────────────────────────────────────────────
    print("\nChapter 261 (1848: Reign of Steel):")
    fix(conn, 261,  1, "Narrator", "neutral")    # "Observing the change, Sunny..."
    fix(conn, 261,  3, "Narrator", "neutral")    # "He continued the wanton slaughter..."
    fix(conn, 261,  5, "Narrator", "neutral")    # "Almost an entire minute passed..."
    fix(conn, 261,  7, "Narrator", "neutral")    # "He had seen something similar..."
    fix(conn, 261,  9, "Narrator", "neutral")    # "And now, his Domain had spread..."
    fix(conn, 261, 11, "Narrator", "neutral")    # "At the end of it all, the Supreme..."
    fix(conn, 261, 16, "Narrator", "neutral")    # "Sunny shivered, suddenly overwhelmed..."
    fix(conn, 261, 29, "Narrator", "neutral")    # "Down below, Sunny's avatar..."
    fix(conn, 261, 40, "Narrator", "neutral")    # "Sunny knew that, one day soon..."
    fix(conn, 261, 41, "Sunny",    "sarcastic")  # inner shadow voice ("What's the matter?")
    fix(conn, 261, 42, "Narrator", "neutral")    # "For once, the words did not bring..."

    conn.execute(
        "UPDATE chapters SET status='diarized', updated_at=datetime('now') WHERE id=261"
    )
    print("  -> Chapter 261 reset to 'diarized'")

    conn.commit()
    conn.close()

    pending_255 = sum(1 for _ in [9,10,13,14,16,27,36,42,44,69])
    pending_261 = sum(1 for _ in [1,3,5,7,9,11,16,29,40,41,42])
    print(f"\nDone. {pending_255} lines in ch255, {pending_261} lines in ch261 "
          f"reset to pending for TTS re-synthesis.")
    print("Re-run the pipeline (TTS + assemble stages) for these chapters to rebuild the audio.")


if __name__ == "__main__":
    main()
