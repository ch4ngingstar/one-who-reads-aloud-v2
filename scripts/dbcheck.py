import sqlite3
DB = r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\data\pipeline.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for r in conn.execute("SELECT id, chapter_index, title, status, error_message FROM chapters WHERE status='error'").fetchall():
    print(f'Error chapter: id={r["id"]} CH{r["chapter_index"]} status={r["status"]}')
    print(f'  Error: {r["error_message"]}')

rows = conn.execute("SELECT status, COUNT(*) as n FROM lines WHERE chapter_id=4 GROUP BY status").fetchall()
print('Lines for error chapter (id=4):')
for r in rows:
    print(f'  {r["status"]}: {r["n"]}')

for r in conn.execute("SELECT id, chapter_index, title, status, total_lines FROM chapters WHERE status='complete' ORDER BY chapter_index").fetchall():
    print(f'Complete: id={r["id"]} CH{r["chapter_index"]} lines={r["total_lines"]} "{r["title"]}"')

# Show first pending chapter that could be tested
r = conn.execute("SELECT id, chapter_index, title FROM chapters WHERE status='pending' ORDER BY chapter_index LIMIT 1").fetchone()
print(f'\nFirst pending: id={r["id"]} CH{r["chapter_index"]} "{r["title"]}"')
conn.close()
