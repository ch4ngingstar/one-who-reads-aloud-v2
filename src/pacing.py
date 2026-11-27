"""Pauses between labelled audiobook lines, shared by speech and sound cues."""

import re

# Silence between two takes after their edge padding has been normalised (see
# speech_audio.tighten_edges: 30 ms lead, 60 ms tail). The paragraph values reproduce
# the narrator flow the owner approved (~0.6 s between paragraphs) and make it the same
# for every engine; the shorter values keep a paragraph's lines together.
NATURAL_PAUSES = {
    "attached": 200,        # '…,' he said — attribution tails and interrupted quotations
    "sentence": 300,        # same voice, same paragraph
    "turn": 380,            # another voice inside one paragraph (an action beat, then a quote)
    "paragraph": 520,       # same voice, next paragraph
    "paragraph_turn": 620,  # another voice, next paragraph (most dialogue exchanges)
}

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _attached(previous: dict, current: dict) -> bool:
    """Attribution tails and interrupted quotations belong to their sentence."""
    if {previous.get("kind"), current.get("kind")} != {"dialogue", "prose"}:
        return False
    before = previous.get("text", "").rstrip()
    after = current.get("text", "").lstrip()
    return before.endswith((",", "—", "–")) or (current.get("kind") == "prose" and after[:1].islower())


def pause_ms(previous: dict, current: dict, same_speaker: int, new_speaker: int,
             pauses: "dict | None" = None) -> int:
    """Gap before `current`. Without `pauses`, the legacy fixed gaps for raw takes."""
    turn = previous["speaker"] != current["speaker"]
    if pauses is None:
        if _attached(previous, current):
            return min(same_speaker, 100)
        return new_speaker if turn else same_speaker
    if _attached(previous, current):
        return pauses["attached"]
    # Unknown paragraph position counts as a new paragraph: the slower, safer reading.
    if current.get("paragraph_start", True):
        return pauses["paragraph_turn" if turn else "paragraph"]
    return pauses["turn" if turn else "sentence"]


def _alnum_index(text: str):
    kept = [(i, c.casefold()) for i, c in enumerate(text) if c.isalnum()]
    return [i for i, _ in kept], "".join(c for _, c in kept)


def mark_paragraphs(lines: list, chapter_texts: list, probe_chars: int = 40) -> list:
    """Set line["paragraph_start"] by finding each line, in order, in the chapter source.

    Lines are pieces of the chapter's paragraphs; quotes, dashes and spacing may differ
    from the source, so matching uses letters and digits only. A line that cannot be
    found (edited text) is treated as a new paragraph and does not move the cursor.
    """
    source = "\n\n".join(chapter_texts)
    positions, flat = _alnum_index(source)
    cursor, previous_end = 0, None
    for line in lines:
        words = "".join(c.casefold() for c in line.get("text", "") if c.isalnum())
        found = flat.find(words[:probe_chars], cursor) if words else -1
        if found < 0:
            line["paragraph_start"] = True
            continue
        end = found + (len(words) if flat.startswith(words, found) else len(words[:probe_chars]))
        start_at = positions[found]
        line["paragraph_start"] = (previous_end is None or
                                   bool(_PARAGRAPH_BREAK.search(source, previous_end, start_at)))
        previous_end, cursor = positions[end - 1] + 1, end
    return lines
