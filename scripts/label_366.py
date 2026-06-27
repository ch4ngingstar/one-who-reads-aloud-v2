import json

# CH_0366 - Chapter 1953 'One Small Step for Shadow' - 35 segments
# Dialogue segments: 9, 11, 12
# Thought segments: 21
# All others: prose -> Narrator
#
# 9: [D] "... Well, what are you waiting for? Chop-chop! Get inside."
#    -> Sunny talking to his gloomy shadow (sarcastic/commanding)
# 10: [P] "The gloomy stared at him in shock, then pointed at itself with a finger, as if asking.."
#    -> Narrator
# 11: [D] "Why, of course. I mean, who else?..." -> Sunny (sarcastic)
# 12: [D] "Of course not. That's the Land of Death, you know!"
#    -> This is the shadow responding (gloomy shadow expressing fear)
#    -> Gloomy is Sunny's shadow - it's an incarnation of Sunny, so label as Sunny
#    -> But wait: seg 13 prose: "The gloomy shadow was dumbstruck for a few moments, then lowered its hands...
#       and slowly clenched its fists, staring at Sunny with a murderous gaze."
#    -> This implies gloomy said seg 12. Gloomy is Sunny's shadow/incarnation -> Sunny
#    -> emotion: frightened (it said "Land of Death, you know!" in protest)
# 21: [T] "Is Shadow Realm... Shadow God's soul sea?" -> Sunny (confused)

labels = []

# 0-8: prose -> Narrator
for i in range(9):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 9: dialogue - Sunny to his shadow (sarcastic/commanding)
labels.append({'i': 9, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 10: prose
labels.append({'i': 10, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 11: dialogue - Sunny (sarcastic)
labels.append({'i': 11, 'speaker': 'Sunny', 'emotion': 'sarcastic'})

# 12: dialogue - Gloomy shadow (Sunny's incarnation, frightened protest)
labels.append({'i': 12, 'speaker': 'Sunny', 'emotion': 'frightened'})

# 13-20: prose
for i in range(13, 21):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

# 21: thought - Sunny (confused/wondering)
labels.append({'i': 21, 'speaker': 'Sunny', 'emotion': 'confused'})

# 22-34: prose
for i in range(22, 35):
    labels.append({'i': i, 'speaker': 'Narrator', 'emotion': 'neutral'})

assert len(labels) == 35, f"Expected 35, got {len(labels)}"

data = {'chapter_id': 366, 'labels': labels}
with open(r'C:\Users\alityan\OneDrive\Desktop\shaodw salve\data\diar_export\ch_0366.labels.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('ch_0366 done:', len(labels), 'labels')
