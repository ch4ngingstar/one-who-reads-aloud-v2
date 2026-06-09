"""Register all voice WAVs from src/data/voices/ into the pipeline DB."""
import sqlite3
from pathlib import Path

BASE = Path(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve")
VOICES_DIR = BASE / "src" / "data" / "voices"
DB = BASE / "src" / "data" / "pipeline.db"

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

for wav in sorted(VOICES_DIR.glob("*.wav")):
    speaker = wav.stem.capitalize()
    path = str(wav)
    conn.execute(
        "INSERT INTO voices (speaker, ref_audio_path) VALUES (?, ?) "
        "ON CONFLICT(speaker) DO UPDATE SET ref_audio_path=excluded.ref_audio_path",
        (speaker, path),
    )
    print(f"  registered: {speaker} -> {wav.name}")

conn.commit()

# Reset errored chapters to pending
cur = conn.execute("UPDATE chapters SET status='pending', error_message=NULL WHERE status='error'")
print(f"\n  reset {cur.rowcount} errored chapter(s) to pending")

conn.close()
print("Done.")
