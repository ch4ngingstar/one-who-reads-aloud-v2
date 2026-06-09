"""
Manual diarization fix for Chapter 1844 (chapter_id=257).
Fixes: duplicates, wrong speakers, Narrator/speech mixed lines, Speaker 'Teacher' -> Julius.
After running: chapter is reset to 'diarized' so pipeline runs TTS+assemble only.
"""
import sqlite3
import re

DB  = r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\src\data\pipeline.db"
CH  = 257

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

cur = {r["line_index"]: dict(r) for r in
       conn.execute("SELECT * FROM lines WHERE chapter_id=? ORDER BY line_index", (CH,))}

def T(i):   return cur[i]["text"]
def E(i):   return cur[i]["emotion"]

def find_speech_q(text):
    """Return index of the speech-introducing ' (preceded by sentence-end + space)."""
    # Match: <period|!|?|en-dash|em-dash> <space> <single-quote>
    for m in re.finditer(r"[.!?–—]\s'", text):
        pos = m.end() - 1       # position of the '
        after = text[pos + 1:]
        # Confirm it starts speech (upper, digit, or "...")
        if after and (after[0].isupper() or after[0] in (".", "…")):
            return pos
    return -1

def split_sp(text):
    """Split 'Narrator prose. 'Speech text' -> (prose, speech). Returns (full, None) if no split."""
    q = find_speech_q(text)
    if q > 0:
        return text[:q].rstrip(". ").strip(), text[q + 1:].strip()
    return text.strip(), None

new_lines = []

def L(spk, emo, txt):
    txt = txt.strip()
    if txt:
        new_lines.append((spk, emo, txt))

# ── Block 1: Opening dialogue  (current 0 wrong, 1 correct, 2-4 Narrator prose) ─
L("Ray",      "neutral",    T(1))   # Ray's line (was duplicated onto Narrator at 0)
L("Narrator", "neutral",    T(2))   # prose "Ray's voice... he sighed." (fix speaker)
L("Ray",      "neutral",    T(5))   # "Have enough decency..."

# ── Block 2: Army-context narration (6-11, skip 12 duplicate of 11) ─────────────
for i in [6, 7, 8, 9, 10, 11]:
    L("Narrator", E(i), T(i))

# ── Block 3: Inner monologue (split 13; skip 14 = exact duplicate of 13) ─────────
narr, speech = split_sp(T(13))
L("Narrator", "neutral",    narr)
if speech: L("Rain", "sarcastic", speech)

# ── Block 4: Cottage narration (15, skip 16 = subset duplicate) ──────────────────
L("Narrator", "neutral", T(15))

# ── Block 5: Line 17 Narrator — trim embedded inner-thought from tail ─────────────
narr, speech = split_sp(T(17))
L("Narrator", "neutral", narr)
# Line 18: Rain "What is that?" — already correct
L("Rain", "confused", T(18))

# ── Block 6: Teacher → Julius ─────────────────────────────────────────────────────
L("Julius", "neutral", T(19))           # line 19

# ── Block 7: Line 20 Rain (contains Narrator prose + Rain's cry) ─────────────────
narr, speech = split_sp(T(20))
L("Narrator", "neutral",   narr)
if speech: L("Rain", "frightened", speech)

# ── Block 8: Line 21 Teacher (contains Narrator prose + Julius one-word reply) ────
narr, speech = split_sp(T(21))
L("Narrator", "neutral", narr)
if speech: L("Julius", "neutral", speech)

# ── Block 9: Line 22 Rain (pure Narrator prose) ───────────────────────────────────
L("Narrator", "neutral", T(22))

# Line 23 Narrator — correct
L("Narrator", "neutral", T(23))

# ── Block 10: Line 24 Rain → Aiko (wrong speaker) ────────────────────────────────
L("Aiko", "confused", T(24))

# Line 25 Narrator — correct
L("Narrator", "neutral", T(25))

# ── Block 11: Lines 26-29 each have Narrator prose + embedded speech ─────────────
for idx, spk, emo in [
    (26, "Aiko", "confused"),
    (27, "Rain", "confused"),
    (28, "Rain", "neutral"),
    (29, "Aiko", "confused"),
]:
    narr, speech = split_sp(T(idx))
    if speech:
        L("Narrator", "neutral", narr)
        L(spk, emo, speech)
    else:
        L(spk, emo, T(idx))

# ── Block 12: Line 30 — 4-way split ──────────────────────────────────────────────
# "Listening...head. 'To answer...assistant.' They turned...simultaneously. 'You have an assistant?"
t30 = T(30)
j_end_marker = "assistant.'"
p_jend = t30.find(j_end_marker)
if p_jend >= 0:
    p_after_julius = p_jend + len(j_end_marker)
    # Find opening ' of Julius speech
    p_julius_open = t30.rfind("'", 0, p_jend)
    if p_julius_open >= 0:
        L("Narrator", "neutral", t30[:p_julius_open].strip())
        julius_txt = t30[p_julius_open + 1 : p_jend + len("assistant.")].strip()
        L("Julius", "neutral", julius_txt)
        rest = t30[p_after_julius:].strip()
        narr2, speech2 = split_sp(rest)
        L("Narrator", "neutral", narr2)
        if speech2: L("Unknown", "confused", speech2)
    else:
        L("Narrator", "neutral", t30)
else:
    L("Narrator", "neutral", t30)

# Line 31 Narrator — correct
L("Narrator", "neutral", T(31))

# ── Block 13: Lines 32-33 Teacher → Julius; 33 needs prose/speech split ──────────
L("Julius", E(32), T(32))
narr, speech = split_sp(T(33))
L("Narrator", "neutral", narr)
if speech: L("Julius", "commanding", speech)

# Lines 34-35 Narrator — correct
L("Narrator", "neutral", T(34))
L("Narrator", "neutral", T(35))

# ── Preview ───────────────────────────────────────────────────────────────────────
print(f"\nNew line count: {len(new_lines)}\n")
for i, (spk, emo, txt) in enumerate(new_lines):
    print(f"[{i:>3}] {spk:<14} ({emo:<12})  {txt[:90]}")

# ── Write to DB ───────────────────────────────────────────────────────────────────
print("\nApplying to DB...")
conn.execute("DELETE FROM lines WHERE chapter_id=?", (CH,))
conn.executemany(
    "INSERT INTO lines (chapter_id, line_index, speaker, text, emotion, status) VALUES (?,?,?,?,?,'pending')",
    [(CH, i, spk, txt, emo) for i, (spk, emo, txt) in enumerate(new_lines)],
)
conn.execute(
    "UPDATE chapters SET status='diarized', total_lines=?, error_message=NULL, "
    "output_audio_path=NULL, output_file_size_bytes=NULL WHERE id=?",
    (len(new_lines), CH),
)
conn.commit()
conn.close()
print(f"Done. {len(new_lines)} lines written, chapter reset to 'diarized'.")
