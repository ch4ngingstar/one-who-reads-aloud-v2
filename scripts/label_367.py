import json

# CH_0367 - Chapter 1954 'Realm of Shadows' - 53 segments
# Thought segments: 22, 30
# All others: prose -> Narrator
#
# 22: [T] "Now, then... should I take a look around?" -> Sunny (cold, cautious)
# 30: [T] "Something... is wrong, I think." -> Sunny (cold/frightened)
# All prose segs: Narrator
# The chapter is pure description of Shadow Realm exploration - no dialogue at all

labels = []

# 0-21: prose -> Narrator
for i in range(22):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 22: thought -> Sunny (cold)
labels.append({'i': 22, 'speaker': 'Sunny', 'emotion': 'cold'})

# 23-29: prose
for i in range(23, 30):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 30: thought -> Sunny (frightened/cold)
labels.append({'i': 30, 'speaker': 'Sunny', 'emotion': 'cold'})

# 31-52: prose
for i in range(31, 53):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 53, f"Expected 53, got {len(labels)}"

data = {'chapter_id': 367, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0367.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0367 done:', len(labels), 'labels')
