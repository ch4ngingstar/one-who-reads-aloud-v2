import json

# CH_0363 - Chapter 1950 'High Sorcerer' - 64 segments
labels = []

# 0-9: prose -> Narrator
for i in range(10):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 10: prose "If he did manage to grasp the"
labels.append({'i': 10, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 11: dialogue 'Why' - Sunny's embedded concept in his musing
labels.append({'i': 11, 'speaker': 'Sunny', 'emotion': 'cold'})

# 12: prose "of weaving instead of only just"
labels.append({'i': 12, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 13: dialogue 'how,'
labels.append({'i': 13, 'speaker': 'Sunny', 'emotion': 'cold'})

# 14-16: prose
for i in range(14, 17):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 17: dialogue 'Why am I even thinking about that?' - Sunny rhetorical/sarcastic
labels.append({'i': 17, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 18-20: prose
for i in range(18, 21):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 21: dialogue "Let's see what mysteries you're hiding!" - Sunny excited (narrated as Rock said it, joke)
labels.append({'i': 21, 'speaker': 'Sunny', 'emotion': 'excited'})

# 22-27: prose
for i in range(22, 28):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 28: dialogue - Aiko
labels.append({'i': 28, 'speaker': 'Aiko', 'emotion': 'confused'})

# 29: prose
labels.append({'i': 29, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 30: dialogue - Sunny (dazed/sarcastic after merging with objects)
labels.append({'i': 30, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 31: prose
labels.append({'i': 31, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 32: dialogue - Sunny
labels.append({'i': 32, 'speaker': 'Sunny', 'emotion': 'cold'})

# 33: prose
labels.append({'i': 33, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 34: dialogue - Aiko
labels.append({'i': 34, 'speaker': 'Aiko', 'emotion': 'neutral'})

# 35: prose
labels.append({'i': 35, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 36: dialogue - Sunny confused
labels.append({'i': 36, 'speaker': 'Sunny', 'emotion': 'confused'})

# 37: dialogue - Aiko neutral
labels.append({'i': 37, 'speaker': 'Aiko', 'emotion': 'neutral'})

# 38-39: prose
for i in range(38, 40):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 40: dialogue - Sunny surprised/excited
labels.append({'i': 40, 'speaker': 'Sunny', 'emotion': 'excited'})

# 41: prose
labels.append({'i': 41, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 42: dialogue - Sunny neutral
labels.append({'i': 42, 'speaker': 'Sunny', 'emotion': 'neutral'})

# 43: prose
labels.append({'i': 43, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 44: dialogue - Aiko neutral
labels.append({'i': 44, 'speaker': 'Aiko', 'emotion': 'neutral'})

# 45: dialogue - Sunny cold
labels.append({'i': 45, 'speaker': 'Sunny', 'emotion': 'cold'})

# 46: prose
labels.append({'i': 46, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 47: dialogue - Sunny sarcastic (war profiteering joke)
labels.append({'i': 47, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 48: dialogue - Aiko angry denial
labels.append({'i': 48, 'speaker': 'Aiko', 'emotion': 'angry'})

# 49: dialogue - Sunny commanding
labels.append({'i': 49, 'speaker': 'Sunny', 'emotion': 'commanding'})

# 50: prose
labels.append({'i': 50, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 51: dialogue - Aiko angry (scowled sternly)
labels.append({'i': 51, 'speaker': 'Aiko', 'emotion': 'angry'})

# 52: prose
labels.append({'i': 52, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 53: dialogue - Sunny impatient/cold
labels.append({'i': 53, 'speaker': 'Sunny', 'emotion': 'cold'})

# 54-60: prose
for i in range(54, 61):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 61: dialogue - Sunny pleased with progress
labels.append({'i': 61, 'speaker': 'Sunny', 'emotion': 'excited'})

# 62-63: prose
for i in range(62, 64):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 64, f"Expected 64, got {len(labels)}"

data = {'chapter_id': 363, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0363.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0363 done:', len(labels), 'labels')
