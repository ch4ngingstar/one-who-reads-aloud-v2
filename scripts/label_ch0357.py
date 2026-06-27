import json

# ch_0357: Chapter 1944 'Footsteps of War' - 60 segments
# POV: Sunny (prose = Narrator)
# Dialogue: Sunny and Cassie conversation
#
# Dialogue mapping:
# seg 13: Cassie - "It has to be connected to family, right?" - neutral/questioning
# seg 19: Cassie - "That is... not exactly what I was hoping for..." - sad/somber
# seg 21: Cassie - "You did not miss it, did you?" - neutral (seg 20 says 'her expression turned somber')
# seg 29: Sunny - "...How many members of the Warden's cohort are still alive?" - cold
# seg 30: Cassie - "Many prominent Awakened of the First Generation perished..." - neutral/commanding
# seg 32: Sunny - "You're not suggesting that we should kidnap Saint Jest, are you?" - cold/sarcastic
# seg 33: Cassie - "Why? Has the old man's amiable act fooled you?" - sarcastic
# seg 36: Cassie - "Good. Because he is more sinister than you can imagine..." - cold/commanding
# seg 38: Sunny - "That might be true, but he is a Saint..." - cold
# seg 40: Cassie - "The war is chaotic. There will be an opportunity, I'm sure." - neutral/determined
# seg 46: Sunny - "These memories... will you show them to Nephis?" - neutral
# seg 56: Sunny - "Rest well, Cas. And... good job. We indeed learned a lot today." - neutral

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
    # seg 13: Cassie - "It has to be connected to family, right?" - neutral/questioning
    {"i":13,"speaker":"Cassie","emotion":"neutral"},
    {"i":14,"speaker":"Narrator","emotion":"neutral"},
    {"i":15,"speaker":"Narrator","emotion":"neutral"},
    {"i":16,"speaker":"Narrator","emotion":"neutral"},
    {"i":17,"speaker":"Narrator","emotion":"neutral"},
    {"i":18,"speaker":"Narrator","emotion":"neutral"},
    # seg 19: Cassie - somber, about Ki Song's Flaw not being exploitable
    {"i":19,"speaker":"Cassie","emotion":"sad"},
    {"i":20,"speaker":"Narrator","emotion":"neutral"},
    # seg 21: Cassie - "You did not miss it, did you?" - neutral
    {"i":21,"speaker":"Cassie","emotion":"neutral"},
    {"i":22,"speaker":"Narrator","emotion":"neutral"},
    {"i":23,"speaker":"Narrator","emotion":"neutral"},
    {"i":24,"speaker":"Narrator","emotion":"neutral"},
    {"i":25,"speaker":"Narrator","emotion":"neutral"},
    {"i":26,"speaker":"Narrator","emotion":"neutral"},
    {"i":27,"speaker":"Narrator","emotion":"neutral"},
    {"i":28,"speaker":"Narrator","emotion":"neutral"},
    # seg 29: Sunny - cold strategic question
    {"i":29,"speaker":"Sunny","emotion":"cold"},
    # seg 30: Cassie - informative/commanding
    {"i":30,"speaker":"Cassie","emotion":"neutral"},
    {"i":31,"speaker":"Narrator","emotion":"neutral"},
    # seg 32: Sunny - sarcastic/questioning about kidnapping Jest
    {"i":32,"speaker":"Sunny","emotion":"sarcastic"},
    # seg 33: Cassie - sarcastic counter-question
    {"i":33,"speaker":"Cassie","emotion":"sarcastic"},
    {"i":34,"speaker":"Narrator","emotion":"neutral"},
    {"i":35,"speaker":"Narrator","emotion":"neutral"},
    # seg 36: Cassie - cold warning about Jest
    {"i":36,"speaker":"Cassie","emotion":"cold"},
    {"i":37,"speaker":"Narrator","emotion":"neutral"},
    # seg 38: Sunny - cold/practical objection
    {"i":38,"speaker":"Sunny","emotion":"cold"},
    {"i":39,"speaker":"Narrator","emotion":"neutral"},
    # seg 40: Cassie - determined but tired
    {"i":40,"speaker":"Cassie","emotion":"neutral"},
    {"i":41,"speaker":"Narrator","emotion":"neutral"},
    {"i":42,"speaker":"Narrator","emotion":"neutral"},
    {"i":43,"speaker":"Narrator","emotion":"neutral"},
    {"i":44,"speaker":"Narrator","emotion":"neutral"},
    {"i":45,"speaker":"Narrator","emotion":"neutral"},
    # seg 46: Sunny - asking about showing memories to Nephis
    {"i":46,"speaker":"Sunny","emotion":"neutral"},
    {"i":47,"speaker":"Narrator","emotion":"neutral"},
    {"i":48,"speaker":"Narrator","emotion":"neutral"},
    {"i":49,"speaker":"Narrator","emotion":"neutral"},
    {"i":50,"speaker":"Narrator","emotion":"neutral"},
    {"i":51,"speaker":"Narrator","emotion":"neutral"},
    {"i":52,"speaker":"Narrator","emotion":"neutral"},
    {"i":53,"speaker":"Narrator","emotion":"neutral"},
    {"i":54,"speaker":"Narrator","emotion":"neutral"},
    {"i":55,"speaker":"Narrator","emotion":"neutral"},
    # seg 56: Sunny - warm farewell to Cassie
    {"i":56,"speaker":"Sunny","emotion":"neutral"},
    {"i":57,"speaker":"Narrator","emotion":"neutral"},
    {"i":58,"speaker":"Narrator","emotion":"neutral"},
    {"i":59,"speaker":"Narrator","emotion":"neutral"},
]

assert len(labels) == 60, f"Expected 60, got {len(labels)}"
data = {"chapter_id": 357, "labels": labels}
with open(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0357.labels.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("ch_0357 done:", len(labels), "labels")
