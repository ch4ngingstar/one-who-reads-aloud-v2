import json

# CH_0364 - Chapter 1951 'The Nuances of Proper Grammar' - 51 segments
# Sunny-POV, mostly prose narration about him studying Divine Memories
# Dialogue segments: 20, 23, 44
# kind=dialogue segments:
#   20: "Yeah... I'm not doing that again any time soon." -> Sunny (cold/relieved)
#   23: "At least I didn't start with Weavers Mask." -> Sunny (sarcastic/cold)
#   44: "Made pale and feeble by the radiance of day. Shadow laughed and rose from the ground."
#       -> seg 45 prose says "That was what the Nightmare Spell called Shadow God in the description of the Lantern."
#       -> This is a quoted rune description text. Rule A5: stat/item readout -> Narrator
#          But it's labeled as dialogue... It's a rune description quoted by the Nightmare Spell.
#          -> The Nightmare Spell (it's describing the lantern's enchantment wording)

labels = []

# 0-19: prose -> Narrator
for i in range(20):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 20: dialogue - Sunny after terror of Shadow Lantern fusion (cold/relieved)
labels.append({'i': 20, 'speaker': 'Sunny', 'emotion': 'cold'})

# 21-22: prose
for i in range(21, 23):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 23: dialogue - Sunny sarcastic reflection
labels.append({'i': 23, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 24-43: prose
for i in range(24, 44):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 44: dialogue - the Nightmare Spell rune description of Shadow Lantern's enchantment
labels.append({'i': 44, 'speaker': 'The Nightmare Spell', 'emotion': 'neutral'})

# 45-50: prose
for i in range(45, 51):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 51, f"Expected 51, got {len(labels)}"

data = {'chapter_id': 364, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0364.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0364 done:', len(labels), 'labels')
