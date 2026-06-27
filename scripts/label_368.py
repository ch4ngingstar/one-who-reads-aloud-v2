import json

# CH_0368 - Chapter 1955 'Rude Welcome' - 53 segments
# Dialogue segments: 30, 33, 35
# Thought segments: 22, 39, 52
# All others: prose -> Narrator
#
# 22: [T] "Well. That's not the best homecoming I could have hoped for, I guess. Not the worst, though, either..."
#     -> Sunny (sarcastic/cold)
# 30: [D] "What are you waiting for, fool? Hurry up and turn back into a shadow."
#     -> Sunny's original body talking to his avatar (commanding/cold)
# 32: prose "The avatar gritted his teeth, lingered for a moment, and then said in a resentful tone:"
#     -> Narrator. Attribution: next dialogue is the avatar (Sunny)
# 33: [D] "Go to hell, you smug bastard!" -> Sunny (avatar, resentful/angry)
# 34: prose "Berating himself was still fun." -> Narrator
# 35: [D] "We're already in hell, though." -> Sunny (sarcastic reply to himself)
#     -> prose 34 says "Berating himself was still fun" - this is the original Sunny replying
# 39: [T] "I'll... need to ponder a bit before venturing into the Shadow Realm again." -> Sunny (cold)
# 52: [T] "What... what the hell have I almost brought back from that cursed place?" -> Sunny (frightened)

labels = []

# 0-21: prose -> Narrator
for i in range(22):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 22: thought -> Sunny sarcastic
labels.append({'i': 22, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 23-29: prose
for i in range(23, 30):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 30: dialogue - Sunny (original) to avatar, commanding
labels.append({'i': 30, 'speaker': 'Sunny', 'emotion': 'commanding'})

# 31-32: prose
for i in range(31, 33):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 33: dialogue - Sunny (avatar, resentful/angry)
labels.append({'i': 33, 'speaker': 'Sunny', 'emotion': 'angry'})

# 34: prose
labels.append({'i': 34, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 35: dialogue - Sunny (original, sarcastic reply)
labels.append({'i': 35, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 36-38: prose
for i in range(36, 39):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 39: thought -> Sunny (cold)
labels.append({'i': 39, 'speaker': 'Sunny', 'emotion': 'cold'})

# 40-51: prose
for i in range(40, 52):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 52: thought -> Sunny (frightened)
labels.append({'i': 52, 'speaker': 'Sunny', 'emotion': 'frightened'})

assert len(labels) == 53, f"Expected 53, got {len(labels)}"

data = {'chapter_id': 368, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0368.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0368 done:', len(labels), 'labels')
