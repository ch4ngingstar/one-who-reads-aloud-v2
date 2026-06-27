import json

# CH_0365 - Chapter 1952 'Choice Paralysis' - 26 segments
# Segments with kind=thought: 0, 3
# All others: prose -> Narrator
# 0: thought "It just doesn't end today!" -> Sunny (excited)
# 3: thought "Who cares about my heart? I have six spare ones, anyway!" -> Sunny (sarcastic)

labels = []

# 0: thought -> Sunny (excited)
labels.append({'i': 0, 'speaker': 'Sunny', 'emotion': 'excited'})

# 1-2: prose
for i in range(1, 3):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 3: thought -> Sunny (sarcastic)
labels.append({'i': 3, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 4-25: prose
for i in range(4, 26):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 26, f"Expected 26, got {len(labels)}"

data = {'chapter_id': 365, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0365.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0365 done:', len(labels), 'labels')
