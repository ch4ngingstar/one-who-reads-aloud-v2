"""Prompt text for the local labeller.

Layout is chosen for llama.cpp's prefix cache: every question about a chapter
shares one long, identical prefix (rules + cast + previous-chapter tail + the whole
chapter, quotes numbered), and only the short question at the end changes. The
chapter is evaluated once; each question costs a few hundred tokens.

Provisional answers are shown only as "previous quoted lines (may contain mistakes)"
and never inside the chapter text, so an early error cannot rewrite the evidence.
"""
from __future__ import annotations

import string

from attribution_evidence import Evidence
from character_bible import Bible

EMOTION_GUIDE = {
    "neutral": "ordinary delivery. THE DEFAULT: pick it unless the text shows otherwise.",
    "whispers": "actually hushed: 'whispered', 'murmured', 'quietly', 'under his breath', hiding.",
    "angry": "snapped, shouted in anger, furious, through gritted teeth.",
    "sad": "grief, sorrow, a breaking voice.",
    "excited": "eager, thrilled, enthusiastic exclamations.",
    "commanding": "an order given with authority ('commanded', 'ordered', a battlefield command). Not every imperative.",
    "frightened": "fear or panic in the voice.",
    "confused": "bewildered, lost, puzzled questions.",
    "pleading": "begging.",
    "cold": "described as icy, flat, emotionless, or unmistakably menacing calm.",
    "laughing": "laughing or chuckling while speaking.",
    "sarcastic": "mocking or sarcastic tone.",
    "desperate": "desperation.",
}
EMOTIONS = list(EMOTION_GUIDE)

SYSTEM = """\
You are a careful reader of the web novel Shadow Slave, working out who speaks every \
quoted line so an audiobook can give each character their own voice. Read the text \
closely; never guess from habit.

How the text works:
- Narration introduces a speaker in the paragraph before the quote: a name or pronoun \
followed by a colon ("Finally, she said in an even tone:") or simply that person's \
action ("Morgan laughed." then Morgan's line). Pronouns must agree in gender.
- A name used to address someone inside a quote ("Sunny, wait!") is usually the \
LISTENER, not the speaker.
- Conversations alternate, but not strictly; a third person can cut in.
- Lines in ‘single quotes’ are inner thoughts of the point-of-view character. Lines in \
[brackets] are Nightmare Spell notifications or telepathic messages between characters. \
Lines in «guillemets» may be speech or thought.
- The point-of-view character often refers to known people by description ("the \
charming young man", "the huntress", "her teacher", "the darkness"). Work out who is \
meant before choosing "someone else"; that option is only for people the story never names.
- A speaker who introduces themselves ("I am Awakened Kim") is that person.
- Unnamed people (soldiers, porters, a stranger, "the Master") are not named characters.

Characters (gender):
{cast}"""


def system_prompt(bible: Bible) -> str:
    cast = []
    for name in bible.names:
        line = f"- {name} ({bible.genders[name]})"
        if bible.notes.get(name):
            line += f": {bible.notes[name]}"
        cast.append(line)
    return SYSTEM.format(cast="\n".join(cast))


def render_segment(segment: dict) -> str:
    text, index = segment["text"], segment["index"]
    if segment["kind"] == "prose":
        return text
    if segment["kind"] == "system":
        return f"[#{index}] {text}"
    if segment.get("hint"):
        return f"[#{index}] «{text}»"
    if segment["kind"] == "thought":
        return f"[#{index}] ‘{text}’"
    return f"[#{index}] “{text}”"


def render_chapter(segments: "list[dict]", title: str, previous_tail: "list[str]") -> str:
    """The chapter as paragraphs, every non-prose segment tagged with its number."""
    lines = []
    if previous_tail:
        lines += ["END OF THE PREVIOUS CHAPTER (context only):", *previous_tail, ""]
    lines.append(f"CHAPTER: {title}")
    paragraph, buffer = None, []
    for segment in segments:
        current = segment.get("paragraph", segment["index"])
        if current != paragraph and buffer:
            lines.append(" ".join(buffer))
            buffer = []
        paragraph = current
        buffer.append(render_segment(segment))
    if buffer:
        lines.append(" ".join(buffer))
    return "\n".join(lines)


def clue_lines(ev: Evidence) -> "list[str]":
    """The rule layer's evidence, phrased as clues (never as orders)."""
    clues = []
    if ev.tag and ev.tag_source == "self":
        clues.append(f"The speaker introduces themselves as {ev.tag}.")
    elif ev.tag:
        clues.append(f"The narration names {ev.tag} as the speaker of this line.")
    elif ev.unnamed:
        clues.append(f"The narration attributes this line to {ev.unnamed.split(' ', 1)[1]} (not a named character).")
    elif ev.gender in ("male", "female"):
        word = "woman or girl" if ev.gender == "female" else "man or boy"
        clues.append(f"The narration introduces this line with a pronoun: the speaker is a {word}.")
    if ev.beat and not ev.tag:
        clues.append(f"The narration right before this line shows {ev.beat} acting; that is often the speaker.")
    elif ev.beat_unnamed and not ev.tag:
        clues.append(f"The narration right before this line shows {ev.beat_unnamed.split(' ', 1)[1]} "
                     "(an unnamed person) acting; that is often the speaker.")
    elif ev.beat_gender in ("male", "female") and not ev.tag and not ev.gender:
        word = "a woman" if ev.beat_gender == "female" else "a man"
        clues.append(f"The narration right before this line shows {word} acting; that is often the speaker.")
    if ev.vocatives:
        clues.append("The line addresses " + ", ".join(ev.vocatives) + " by name, so they are probably the listener.")
    if ev.same_paragraph_as_previous_quote:
        clues.append("This line shares a paragraph with the previous quote, usually the same speaker continuing.")
    elif ev.follows_quote is not None:
        clues.append(f"It directly follows line [#{ev.follows_quote}] with no narration between: in a "
                     "back-and-forth exchange the reply usually comes from the other person.")
    return clues


def letters(n: int) -> str:
    return string.ascii_uppercase[:n]


def _with_article(group: str) -> str:
    """'laborers' -> 'one of the laborers', 'man' -> 'the man', "Ling's dad" stays."""
    if group[:1].isupper() or group.split()[0].lower() in ("his", "her", "their"):
        return group
    return f"one of the {group}" if group.endswith("s") and not group.endswith("ss") else f"the {group}"


def describe_option(option: str, bible: Bible, groups: "list[str] | None" = None) -> str:
    if option == "@other":
        if groups:
            return "an unnamed person, such as " + " / ".join(_with_article(g) for g in groups) + \
                " (not a named character)"
        return "someone else (an unnamed or unlisted person)"
    gender = bible.genders.get(option)
    return f"{option} ({gender})" if gender in ("male", "female") else option


def speaker_question(segment: dict, ev: Evidence, bible: Bible, options: "list[str]",
                     recent: "list[tuple[int, str]]", *, thought: bool = False, clues: bool = True) -> str:
    verb = "thinks" if thought else "says"
    lines = [f"QUESTION: Who {verb} the line marked [#{segment['index']}]?",
             f"Line [#{segment['index']}]: {segment['text']}"]
    found = clue_lines(ev) if clues else []
    if found:
        lines.append("Clues: " + " ".join(found))
    if recent:
        lines.append("Speakers of the previous quoted lines (may contain mistakes): "
                     + ", ".join(f"#{i} {name}" for i, name in recent))
    lines.append("Options:")
    speakers = {name for _, name in recent}
    for letter, option in zip(letters(len(options)), options):
        text = describe_option(option, bible, ev.groups)
        if (option != "@other" and ev.on_stage is not None and option not in ev.on_stage
                and option not in speakers):
            text += " - only talked about nearby, not shown in the scene"
        lines.append(f"{letter}) {text}")
    lines.append("Answer with the letter only.")
    return "\n".join(lines)


KIND_OPTIONS = ["speech", "thought", "telepathy", "narration", "narration"]


def kind_question(segment: dict, surroundings: str = "") -> str:
    if segment["kind"] == "prose":
        opening = (f"QUESTION: Line [#{segment['index']}] is printed as narration but says 'I' or 'you', "
                   "so its quote marks may have been lost. What is it?")
    else:
        opening = f"QUESTION: The quote marks around [#{segment['index']}] are unreliable. What is it?"
    lines = [opening, f"Line [#{segment['index']}]: {segment['text']}"]
    if surroundings:
        lines.append(surroundings)
    lines += ["Speech is heard: someone answers or reacts to it, or the narration says it was said. "
              "A thought is the point-of-view character's private reaction that nobody hears.",
              "Options:", "A) spoken aloud", "B) a silent inner thought",
              "C) a telepathic or mental message sent to someone else",
              "D) plain narration (not a quote at all)",
              "E) written text being read: a letter, note, file or inscription",
              "Answer with the letter only."]
    return "\n".join(lines)


SYSTEM_OPTIONS = ["system", "telepathy", "narration"]


def system_question(segment: dict) -> str:
    return (f"QUESTION: What is the bracketed line [#{segment['index']}]?\n"
            f"Line [#{segment['index']}]: {segment['text']}\n"
            "Options:\nA) a Nightmare Spell notification\n"
            "B) a telepathic or mental message from a character\n"
            "C) written text or a readout the narrator reads\nAnswer with the letter only.")


def unnamed_question(segment: dict) -> str:
    return (f"QUESTION: The line [#{segment['index']}] is spoken by an unnamed or unlisted person.\n"
            f"Line [#{segment['index']}]: {segment['text']}\n"
            "Describe them in at most three words as the text does (e.g. young knight, porter, "
            "female soldier), or give their name if the text names them, then their gender.\n"
            "Answer exactly as: description | male/female/unknown")


def emotion_question(segment: dict, speaker: str, cues: "list[str]") -> str:
    lines = [f"QUESTION: How does {speaker} deliver the line [#{segment['index']}]?",
             f"Line [#{segment['index']}]: {segment['text']}"]
    if cues:
        lines.append("Delivery words in the narration around it: " + ", ".join(cues))
    lines.append("Judge only from the text around this line, never from the character's usual personality.")
    lines.append("Options:")
    lines += [f"{letter}) {emotion} - {EMOTION_GUIDE[emotion]}" for letter, emotion in zip(letters(len(EMOTIONS)), EMOTIONS)]
    lines.append("Answer with the letter only.")
    return "\n".join(lines)
