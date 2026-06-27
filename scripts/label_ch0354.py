import json

# ch_0354: Chapter 1941 'Children of a New Era' - 73 segments
labels = [
    {"i":0,"speaker":"Narrator","emotion":"neutral"},
    {"i":1,"speaker":"Narrator","emotion":"neutral"},
    {"i":2,"speaker":"Narrator","emotion":"neutral"},
    {"i":3,"speaker":"Narrator","emotion":"neutral"},
    # seg 4: unnamed blonde Awakened - insincere warm greeting - The Legacy Noble (clan squatter type)
    {"i":4,"speaker":"The Legacy Noble","emotion":"neutral"},
    {"i":5,"speaker":"Narrator","emotion":"neutral"},
    {"i":6,"speaker":"Narrator","emotion":"neutral"},
    {"i":7,"speaker":"Narrator","emotion":"neutral"},
    # seg 8: Ki Song - "Where else would I be? This is my Citadel." - commanding
    {"i":8,"speaker":"Ki Song","emotion":"commanding"},
    {"i":9,"speaker":"Narrator","emotion":"neutral"},
    # seg 10: The Legacy Noble - condescending cold threat
    {"i":10,"speaker":"The Legacy Noble","emotion":"cold"},
    {"i":11,"speaker":"Narrator","emotion":"neutral"},
    {"i":12,"speaker":"Narrator","emotion":"neutral"},
    # seg 13: Ki Song - accusing cold question
    {"i":13,"speaker":"Ki Song","emotion":"cold"},
    {"i":14,"speaker":"Narrator","emotion":"neutral"},
    # seg 15: Ki Song - accusing everyone - angry
    {"i":15,"speaker":"Ki Song","emotion":"angry"},
    {"i":16,"speaker":"Narrator","emotion":"neutral"},
    # seg 17: Ki Song - angry accusation
    {"i":17,"speaker":"Ki Song","emotion":"angry"},
    {"i":18,"speaker":"Narrator","emotion":"neutral"},
    # seg 19: The Legacy Noble - threatening/cold
    {"i":19,"speaker":"The Legacy Noble","emotion":"cold"},
    {"i":20,"speaker":"Narrator","emotion":"neutral"},
    {"i":21,"speaker":"Narrator","emotion":"neutral"},
    # seg 22: Ki Song - cold refusal
    {"i":22,"speaker":"Ki Song","emotion":"cold"},
    {"i":23,"speaker":"Narrator","emotion":"neutral"},
    # seg 24: prose with embedded quotes - Narrator
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
    {"i":38,"speaker":"Narrator","emotion":"neutral"},
    {"i":39,"speaker":"Narrator","emotion":"neutral"},
    {"i":40,"speaker":"Narrator","emotion":"neutral"},
    {"i":41,"speaker":"Narrator","emotion":"neutral"},
    {"i":42,"speaker":"Narrator","emotion":"neutral"},
    {"i":43,"speaker":"Narrator","emotion":"neutral"},
    {"i":44,"speaker":"Narrator","emotion":"neutral"},
    {"i":45,"speaker":"Narrator","emotion":"neutral"},
    {"i":46,"speaker":"Narrator","emotion":"neutral"},
    {"i":47,"speaker":"Narrator","emotion":"neutral"},
    {"i":48,"speaker":"Narrator","emotion":"neutral"},
    {"i":49,"speaker":"Narrator","emotion":"neutral"},
    {"i":50,"speaker":"Narrator","emotion":"neutral"},
    # seg 51: Ki Song - calm/neutral after massacre
    {"i":51,"speaker":"Ki Song","emotion":"neutral"},
    {"i":52,"speaker":"Narrator","emotion":"neutral"},
    {"i":53,"speaker":"Narrator","emotion":"neutral"},
    {"i":54,"speaker":"Narrator","emotion":"neutral"},
    # seg 55: Orum - shaken/frightened
    {"i":55,"speaker":"The Bureaucrat","emotion":"frightened"},
    {"i":56,"speaker":"Narrator","emotion":"neutral"},
    {"i":57,"speaker":"Narrator","emotion":"neutral"},
    # seg 58: Ki Song - sad/matter-of-fact
    {"i":58,"speaker":"Ki Song","emotion":"sad"},
    {"i":59,"speaker":"Narrator","emotion":"neutral"},
    # seg 60: Ki Song - cold
    {"i":60,"speaker":"Ki Song","emotion":"cold"},
    {"i":61,"speaker":"Narrator","emotion":"neutral"},
    # seg 62: Ki Song - cold
    {"i":62,"speaker":"Ki Song","emotion":"cold"},
    {"i":63,"speaker":"Narrator","emotion":"neutral"},
    {"i":64,"speaker":"Narrator","emotion":"neutral"},
    {"i":65,"speaker":"Narrator","emotion":"neutral"},
    # seg 66: Orum - angry scolding
    {"i":66,"speaker":"The Bureaucrat","emotion":"angry"},
    {"i":67,"speaker":"Narrator","emotion":"neutral"},
    # seg 68: Ki Song - neutral/curious about her aspect
    {"i":68,"speaker":"Ki Song","emotion":"neutral"},
    {"i":69,"speaker":"Narrator","emotion":"neutral"},
    {"i":70,"speaker":"Narrator","emotion":"neutral"},
    {"i":71,"speaker":"Narrator","emotion":"neutral"},
    # seg 72: Ki Song - cold satisfaction
    {"i":72,"speaker":"Ki Song","emotion":"cold"},
]

assert len(labels) == 73, f"Expected 73, got {len(labels)}"
data = {"chapter_id": 354, "labels": labels}
with open(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0354.labels.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("ch_0354 done:", len(labels), "labels")
