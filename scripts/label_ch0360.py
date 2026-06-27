import json

# ch_0360: Chapter 1947 'Formlessness' - 38 segments
# POV: Sunny - pure narrative about Shadow Dance theory, experimentation with Shadows
# No dialogue, no [T] thought segments
# All prose = Narrator

labels = [
    {"i":0,"speaker":"Narrator","emotion":"neutral"},
    {"i":1,"speaker":"Narrator","emotion":"neutral"},
    {"i":2,"speaker":"Narrator","emotion":"neutral"},
    {"i":3,"speaker":"Narrator","emotion":"neutral"},
    {"i":4,"speaker":"Narrator","emotion":"neutral"},
    {"i":5,"speaker":"Narrator","emotion":"neutral"},
    {"i":6,"speaker":"Narrator","emotion":"neutral"},
    {"i":7,"speaker":"Narrator","emotion":"neutral"},
    {"i":8,"speaker":"Narrator","emotion":"neutral"},
    {"i":9,"speaker":"Narrator","emotion":"neutral"},
    {"i":10,"speaker":"Narrator","emotion":"neutral"},
    {"i":11,"speaker":"Narrator","emotion":"neutral"},
    {"i":12,"speaker":"Narrator","emotion":"neutral"},
    {"i":13,"speaker":"Narrator","emotion":"neutral"},
    {"i":14,"speaker":"Narrator","emotion":"neutral"},
    {"i":15,"speaker":"Narrator","emotion":"neutral"},
    {"i":16,"speaker":"Narrator","emotion":"neutral"},
    {"i":17,"speaker":"Narrator","emotion":"neutral"},
    {"i":18,"speaker":"Narrator","emotion":"neutral"},
    {"i":19,"speaker":"Narrator","emotion":"neutral"},
    {"i":20,"speaker":"Narrator","emotion":"neutral"},
    {"i":21,"speaker":"Narrator","emotion":"neutral"},
    {"i":22,"speaker":"Narrator","emotion":"neutral"},
    {"i":23,"speaker":"Narrator","emotion":"neutral"},
    {"i":24,"speaker":"Narrator","emotion":"neutral"},
    {"i":25,"speaker":"Narrator","emotion":"neutral"},
    {"i":26,"speaker":"Narrator","emotion":"neutral"},
    {"i":27,"speaker":"Narrator","emotion":"neutral"},
    {"i":28,"speaker":"Narrator","emotion":"neutral"},
    {"i":29,"speaker":"Narrator","emotion":"neutral"},
    {"i":30,"speaker":"Narrator","emotion":"neutral"},
    {"i":31,"speaker":"Narrator","emotion":"neutral"},
    {"i":32,"speaker":"Narrator","emotion":"neutral"},
    {"i":33,"speaker":"Narrator","emotion":"neutral"},
    {"i":34,"speaker":"Narrator","emotion":"neutral"},
    {"i":35,"speaker":"Narrator","emotion":"neutral"},
    {"i":36,"speaker":"Narrator","emotion":"neutral"},
    {"i":37,"speaker":"Narrator","emotion":"neutral"},
]

assert len(labels) == 38, f"Expected 38, got {len(labels)}"
data = {"chapter_id": 360, "labels": labels}
with open(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0360.labels.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("ch_0360 done:", len(labels), "labels")
