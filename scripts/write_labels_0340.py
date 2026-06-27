import json

# CH_0340 - Chapter 1927 'Blind Seer' - Sunny POV (in Cassie's shared memory) - 43 segments
# All segments are [P] prose except none marked [D] or [T].
# The dialogue in segs 30, 34 is presented inside guillemets in [P] prose -> Narrator
# (the [P] kind means these are narrated descriptions of the memory experience, not standalone dialogue)
# Seg 35: [P] 'It was Anvil, the King of Swords.' -> Narrator confirming identity
# All [P] throughout this chapter = Narrator narrating the memory experience.
labels_0340 = [
    {'i': 0, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 1, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 2, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 3, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 4, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 5, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 6, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 7, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 8, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 9, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 10, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 11, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 12, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 13, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 14, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 15, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 16, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 17, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 18, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 19, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 20, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 21, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 22, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 23, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 24, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 25, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 26, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 27, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 28, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 29, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 30, 'speaker': 'Narrator', 'emotion': 'neutral'},  # [P] prose with guillemet quote: Anvil's words embedded
    {'i': 31, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 32, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 33, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 34, 'speaker': 'Narrator', 'emotion': 'neutral'},  # [P] prose with guillemet quote: Cassie's response
    {'i': 35, 'speaker': 'Narrator', 'emotion': 'neutral'},  # [P] 'It was Anvil, the King of Swords.'
    {'i': 36, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 37, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 38, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 39, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 40, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 41, 'speaker': 'Narrator', 'emotion': 'neutral'},
    {'i': 42, 'speaker': 'Narrator', 'emotion': 'neutral'},
]
assert len(labels_0340) == 43
with open(r'data/diar_export/ch_0340.labels.json', 'w', encoding='utf-8') as f:
    json.dump({'chapter_id': 340, 'labels': labels_0340}, f, ensure_ascii=False)
print('ch_0340 done:', len(labels_0340))
