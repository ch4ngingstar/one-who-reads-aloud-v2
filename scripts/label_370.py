import json

# CH_0370 - Chapter 1957 "Sorcerer's to do list" - 35 segments
# All prose (kind=prose) - this chapter is guillemet-quoted speech embedded in prose.
# No [D] or [T] segments. All kind=prose -> Narrator per rules.
# Guillemet-quoted inner speech is still prose kind -> Narrator.

labels = []

for i in range(35):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 35, f"Expected 35, got {len(labels)}"

data = {'chapter_id': 370, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0370.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0370 done:', len(labels), 'labels')
