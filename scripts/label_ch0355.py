import json

# ch_0355: Chapter 1942 'Master Orum' - 74 segments
# Two-part structure:
# Part 1 (0-42): Flashback via Cassie's memory-sharing. Orum at the Academy cafeteria.
#   POV-ish: third person narrating Orum's memory
#   Speakers: Orum (The Bureaucrat), Ki Song (roster), Broken Sword (Unknown - not on roster),
#             Smile of Heaven (Unknown - not on roster), Anvil (roster)
# Part 2 (43-73): Present day. Sunny in Cassie's cell, then Cassie + Anvil interrogating Orum.
#   POV: Sunny's present (prose=Narrator)
#   Speakers: Cassie, Anvil, Orum (The Bureaucrat)
#
# Broken Sword = not on roster -> Unknown
# Smile of Heaven = not on roster -> Unknown
# Asterion = on roster!
#
# Dialogue mapping:
# seg 14: Orum - "Awakened Song. It is so nice to see you..." - neutral/polite
# seg 16: Ki Song - "Master Orum! I didn't expect to run into you here..." - excited/warm
# seg 17: Orum - "My niece has just conquered her First Nightmare..." - neutral
# seg 19: Ki Song - "No. I am meeting a few colleagues..." - neutral
# seg 22: Orum - "Well, I'll scold them if you want..." - neutral
# seg 30: Broken Sword (Unknown) - "Awakened Song. Please forgive us for being late." - neutral
# seg 32: Smile of Heaven (Unknown) - "Song! I haven't seen you in ages..." - excited
# seg 37: Broken Sword (Unknown) - "Congratulations! I hear you're a father now..." - excited
# seg 39: Anvil - "Well. Yes. In any case... we should discuss the preparations..." - cold/neutral
# seg 41: Anvil - "This is Asterion..." - neutral
# seg 48: Cassie - "...l have learned what you asked for, Your Majesty." - neutral
# seg 50: Cassie - "For what it's worth, Master Orum's family does not seem to be aware..." - neutral
# seg 53: Anvil - "...Was it worth it, teacher?" - cold
# seg 56: Orum - "Worth it? Sure... I guess it was." - cold/resigned
# seg 58: Anvil - "You are a fool. She is a monster..." - cold
# seg 60: Orum - "A monster? All of you are monsters..." - angry/defiant
# seg 63: Orum - "...What have you done? What kind of heartless world..." - desperate/sad
# seg 72: Anvil - "Lady Cassia... there are more prisoners waiting to be interrogated." - commanding

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
    # seg 14: Orum - polite/formal greeting to Ki Song
    {"i":14,"speaker":"The Bureaucrat","emotion":"neutral"},
    {"i":15,"speaker":"Narrator","emotion":"neutral"},
    # seg 16: Ki Song - warm, excited to see him
    {"i":16,"speaker":"Ki Song","emotion":"excited"},
    # seg 17: Orum - explaining why he's at the Academy
    {"i":17,"speaker":"The Bureaucrat","emotion":"neutral"},
    {"i":18,"speaker":"Narrator","emotion":"neutral"},
    # seg 19: Ki Song - slightly dissatisfied about colleagues being late
    {"i":19,"speaker":"Ki Song","emotion":"neutral"},
    {"i":20,"speaker":"Narrator","emotion":"neutral"},
    {"i":21,"speaker":"Narrator","emotion":"neutral"},
    # seg 22: Orum - politely excusing himself
    {"i":22,"speaker":"The Bureaucrat","emotion":"neutral"},
    {"i":23,"speaker":"Narrator","emotion":"neutral"},
    {"i":24,"speaker":"Narrator","emotion":"neutral"},
    {"i":25,"speaker":"Narrator","emotion":"neutral"},
    {"i":26,"speaker":"Narrator","emotion":"neutral"},
    {"i":27,"speaker":"Narrator","emotion":"neutral"},
    {"i":28,"speaker":"Narrator","emotion":"neutral"},
    {"i":29,"speaker":"Narrator","emotion":"neutral"},
    # seg 30: Broken Sword (not on roster) -> Unknown - formal apology
    {"i":30,"speaker":"Unknown","emotion":"neutral"},
    {"i":31,"speaker":"Narrator","emotion":"neutral"},
    # seg 32: Smile of Heaven (not on roster) -> Unknown - excited/friendly
    {"i":32,"speaker":"Unknown","emotion":"excited"},
    {"i":33,"speaker":"Narrator","emotion":"neutral"},
    {"i":34,"speaker":"Narrator","emotion":"neutral"},
    {"i":35,"speaker":"Narrator","emotion":"neutral"},
    {"i":36,"speaker":"Narrator","emotion":"neutral"},
    # seg 37: Broken Sword (Unknown) - teasing Anvil about being a father - laughing
    {"i":37,"speaker":"Unknown","emotion":"laughing"},
    {"i":38,"speaker":"Narrator","emotion":"neutral"},
    # seg 39: Anvil - getting to business - cold/neutral
    {"i":39,"speaker":"Anvil","emotion":"cold"},
    {"i":40,"speaker":"Narrator","emotion":"neutral"},
    # seg 41: Anvil - introducing Asterion - neutral
    {"i":41,"speaker":"Anvil","emotion":"neutral"},
    {"i":42,"speaker":"Narrator","emotion":"neutral"},
    # --- Present day starts ---
    {"i":43,"speaker":"Narrator","emotion":"neutral"},
    {"i":44,"speaker":"Narrator","emotion":"neutral"},
    {"i":45,"speaker":"Narrator","emotion":"neutral"},
    {"i":46,"speaker":"Narrator","emotion":"neutral"},
    {"i":47,"speaker":"Narrator","emotion":"neutral"},
    # seg 48: Cassie - reporting to Anvil - neutral
    {"i":48,"speaker":"Cassie","emotion":"neutral"},
    {"i":49,"speaker":"Narrator","emotion":"neutral"},
    # seg 50: Cassie - adding about Helie's loyalty - neutral
    {"i":50,"speaker":"Cassie","emotion":"neutral"},
    {"i":51,"speaker":"Narrator","emotion":"neutral"},
    {"i":52,"speaker":"Narrator","emotion":"neutral"},
    # seg 53: Anvil - cold/bitter question to Orum
    {"i":53,"speaker":"Anvil","emotion":"cold"},
    {"i":54,"speaker":"Narrator","emotion":"neutral"},
    {"i":55,"speaker":"Narrator","emotion":"neutral"},
    # seg 56: Orum - resigned/dark - "Worth it? Sure..."
    {"i":56,"speaker":"The Bureaucrat","emotion":"cold"},
    {"i":57,"speaker":"Narrator","emotion":"neutral"},
    # seg 58: Anvil - cold judgment "You are a fool. She is a monster..."
    {"i":58,"speaker":"Anvil","emotion":"cold"},
    {"i":59,"speaker":"Narrator","emotion":"neutral"},
    # seg 60: Orum - defiant/angry "A monster? All of you are monsters..."
    {"i":60,"speaker":"The Bureaucrat","emotion":"angry"},
    {"i":61,"speaker":"Narrator","emotion":"neutral"},
    {"i":62,"speaker":"Narrator","emotion":"neutral"},
    # seg 63: Orum - sad/desperate final question
    {"i":63,"speaker":"The Bureaucrat","emotion":"sad"},
    {"i":64,"speaker":"Narrator","emotion":"neutral"},
    {"i":65,"speaker":"Narrator","emotion":"neutral"},
    {"i":66,"speaker":"Narrator","emotion":"neutral"},
    {"i":67,"speaker":"Narrator","emotion":"neutral"},
    {"i":68,"speaker":"Narrator","emotion":"neutral"},
    {"i":69,"speaker":"Narrator","emotion":"neutral"},
    {"i":70,"speaker":"Narrator","emotion":"neutral"},
    {"i":71,"speaker":"Narrator","emotion":"neutral"},
    # seg 72: Anvil - formal/commanding to Cassie
    {"i":72,"speaker":"Anvil","emotion":"commanding"},
    {"i":73,"speaker":"Narrator","emotion":"neutral"},
]

assert len(labels) == 74, f"Expected 74, got {len(labels)}"
data = {"chapter_id": 355, "labels": labels}
with open(r"C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0355.labels.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("ch_0355 done:", len(labels), "labels")
