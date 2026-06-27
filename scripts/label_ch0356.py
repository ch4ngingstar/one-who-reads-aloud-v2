import json

# ch_0356: Chapter 1943 'Raven Queen' - 42 segments
# POV: Sunny - processing Cassie's memory share
# Segment 25 is [T] thought = Sunny's inner thought
# All [P] prose = Narrator
# No dialogue in this chapter - it's pure Sunny reflection/analysis
# seg 25 [T]: "If you know the enemy and know yourself..." - Sunny's thought, cold (stoic)

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
    # seg 25: [T] Sunny's thought - quote about knowing enemy/self - cold/calculating
    {"i":25,"speaker":"Sunny","emotion":"cold"},
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
    {"i":38,"speaker":"Narrator","emotion":"neutral"},
    {"i":39,"speaker":"Narrator","emotion":"neutral"},
    {"i":40,"speaker":"Narrator","emotion":"neutral"},
    {"i":41,"speaker":"Narrator","emotion":"neutral"},
]

assert len(labels) == 42, f"Expected 42, got {len(labels)}"
data = {"chapter_id": 356, "labels": labels}
with open(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0356.labels.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("ch_0356 done:", len(labels), "labels")
