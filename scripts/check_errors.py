import sqlite3

db = r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\data\pipeline.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT chapter_index, title, status, error_message FROM chapters WHERE status='error'"
).fetchall()

for r in rows:
    print(f"\nCH{r['chapter_index']} [{r['title']}]")
    print(f"  error: {r['error_message']}")

if not rows:
    print("No errored chapters found.")

conn.close()
