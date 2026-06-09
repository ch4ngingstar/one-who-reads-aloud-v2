"""
Reset errored chapters. If diarized lines already exist in DB, set status to
'diarized' (skip LLM re-run). Otherwise reset to 'pending'.
"""
import sqlite3

DB = r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\data\pipeline.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

errored = conn.execute(
    "SELECT id, chapter_index, title FROM chapters WHERE status='error'"
).fetchall()

for ch in errored:
    line_count = conn.execute(
        "SELECT COUNT(*) as n FROM lines WHERE chapter_id=?", (ch["id"],)
    ).fetchone()["n"]

    if line_count > 0:
        new_status = "diarized"
    else:
        new_status = "pending"

    conn.execute(
        "UPDATE chapters SET status=?, error_message=NULL WHERE id=?",
        (new_status, ch["id"]),
    )
    print(f"  CH{ch['chapter_index']} [{ch['title']}]: {line_count} lines -> reset to '{new_status}'")

conn.commit()
conn.close()
print("Done.")
