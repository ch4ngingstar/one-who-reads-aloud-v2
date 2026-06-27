import json

# CH_0369 - Chapter 1956 'Consider Death' - 50 segments
# Dialogue segments: 11, 48
# All others: prose -> Narrator
#
# 11: [D] "Well. I'm still alive, aren't I?" -> Sunny (sarcastic/cold, rhetorical)
# 48: [D] "Now that is really terrifying." -> Sunny (cold - after thinking about his soul being a seed of Shadow Realm)
#     -> prose 49: "Shivering, Sunny threw these thoughts out of his head" confirms it's Sunny

labels = []

# 0-10: prose -> Narrator
for i in range(11):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 11: dialogue - Sunny sarcastic
labels.append({'i': 11, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 12-47: prose
for i in range(12, 48):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 48: dialogue - Sunny cold (frightened really, but Sunny keeps it cold)
labels.append({'i': 48, 'speaker': 'Sunny', 'emotion': 'cold'})

# 49: prose
labels.append({'i': 49, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 50, f"Expected 50, got {len(labels)}"

data = {'chapter_id': 369, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0369.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0369 done:', len(labels), 'labels')
