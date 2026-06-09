"""Quick status overview of chapter progress."""
import sqlite3
from collections import Counter

DB = r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\data\pipeline.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Chapter summary
rows = conn.execute("SELECT status, COUNT(*) as n FROM chapters GROUP BY status").fetchall()
print("Chapter status breakdown:")
for r in rows:
    print(f"  {r['status']}: {r['n']}")

# Voice map
print("\nRegistered voices:")
for r in conn.execute("SELECT speaker, ref_audio_path FROM voices").fetchall():
    print(f"  {r['speaker']}: {r['ref_audio_path'].split(chr(92))[-1]}")

# First 5 chapters detail
print("\nFirst 8 chapters:")
for r in conn.execute("SELECT chapter_index, title, status FROM chapters ORDER BY chapter_index LIMIT 8").fetchall():
    print(f"  CH{r['chapter_index']:>3} | {r['status']:<10} | {r['title']}")

conn.close()
