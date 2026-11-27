"""Turn a labeller's chapter file into the chapter's stored text and lines.

The chapter's chunks are first replaced with the complete EPUB text (volumes 8-9 had
lost ~15% of their paragraphs), then every segment becomes one line: narration for
the narrator, quotes for the labelled speaker. The labeller's decision is kept in
``lines.attribution`` (method, votes, gender) so a reviewer can see why, and lines
the labeller was unsure of carry a ``review_reason``. Hand-locked lines survive
(StateManager.save_diarized_lines keeps them).

A speaker without a cast voice (an unnamed soldier, a minor named character) gets a
gender-matched stand-in voice in ``attribution.voice_as`` instead of falling back to
the narrator's voice.
"""
from __future__ import annotations

import hashlib
import re

from book_text import replace_chunks
from casting import choose_voice
from character_bible import NARRATOR, SPELL, UNNAMED_PREFIX
from segmenter import segment_chunk

DB_KIND = {"speech": "dialogue", "telepathy": "dialogue", "thought": "thought",
           "system": "system", "narration": "prose"}

_NOBLE = re.compile(r"noble|lord|lady|clan|aristocrat|heir|prince|courtier|envoy|herald", re.I)
_MONSTER = re.compile(r"monster|creature|abomination|demon|beast|horror|nightmare", re.I)
_WANDERER = re.compile(r"scaveng|sleeper|surviv|slave|wanderer|refugee|laborer|labourer|porter|worker|"
                       r"villager|pilgrim|beggar|child|kid|boy|girl", re.I)


class StaleLabels(Exception):
    """The labels were made from a different text than the chapter has now."""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stand_in(speaker: str, gender: str, voices: dict) -> "str | None":
    """A cast voice for a speaker who has none of their own; None when they do."""
    if speaker in (NARRATOR, SPELL) or not choose_voice(speaker, "neutral", voices).fallback:
        return None
    role = speaker[len(UNNAMED_PREFIX):] if speaker.startswith(UNNAMED_PREFIX) else ""
    if _MONSTER.search(role):
        choice = "The Nightmare Abomination"
    elif gender == "female":
        choice = "The Bureaucrat"          # the one female stand-in in the cast
    elif _NOBLE.search(role):
        choice = "The Legacy Noble"
    elif _WANDERER.search(role):
        choice = "The Dream Realm Wanderer"
    else:
        choice = "The Hardened Awakened"
    return choice if not choose_voice(choice, "neutral", voices).fallback else None


def build_lines(segments: "list[dict]", labels: "list[dict]", voices: dict, method: str) -> "list[dict]":
    by_index = {label["index"]: label for label in labels}
    lines = []
    for segment in segments:
        label = by_index.get(segment["index"])
        line = {"line_index": segment["index"], "text": segment["text"]}
        if label is None or label["kind"] == "narration":
            line.update(speaker=NARRATOR, emotion="neutral", kind="prose")
            if label is not None:
                line["attribution"] = {"method": f"{method}:{label.get('how') or 'kind'}", "cue_indices": []}
        else:
            speaker = label["speaker"]
            attribution = {"method": f"{method}:{label.get('how') or 'kind'}", "cue_indices": [],
                           "gender": label.get("gender", "unknown"), "votes": label.get("votes", [])}
            voice_as = stand_in(speaker, label.get("gender", "unknown"), voices)
            if voice_as:
                attribution["voice_as"] = voice_as
            line.update(speaker=speaker, emotion=label.get("emotion") or "neutral",
                        kind=DB_KIND.get(label["kind"], "dialogue"), attribution=attribution)
            note = review_note(label)
            if note:
                line["review_reason"] = note
                attribution["review"] = True
        lines.append(line)
    if lines and not any("attribution" in line for line in lines):
        # A chapter without quotes still records who labelled it, so it is not relabelled again.
        lines[0]["attribution"] = {"method": f"{method}:chapter", "cue_indices": []}
    return lines


def review_note(label: dict) -> "str | None":
    """Why a line needs a human look, or None when the labellers agree.

    Measured on the held-out set: lines where Qwen's two blind votes agree AND Gemma
    independently agrees were 98.4% right; everything else is where the errors live.
    """
    if label.get("review"):
        return label["review"]
    if label.get("how") not in (None, "agree", "kind"):
        votes = ", ".join(_display(v) for v in label.get("votes", []) if v)
        return f"Speaker unsure: the labeller's votes split ({votes})."
    second = label.get("gemma")
    if second and not _same_choice(second, label):
        return f"Speaker unsure: a second opinion picked {_display(second)} instead of {_display(label['speaker'])}."
    return None


def _same_choice(vote: str, label: dict) -> bool:
    """A vote for "someone else" agrees with any speaker that was not on the candidate list
    (an unnamed porter, a newly found name such as Carel)."""
    if vote == "@other":
        return label["speaker"] not in label.get("options", [])
    return vote == label["speaker"]


def _display(name: str) -> str:
    return "an unnamed person" if name == "@other" else name


def import_chapter(sm, con, record: dict, voices: dict) -> int:
    """Store one labelled chapter. Returns the number of lines written."""
    chapter_id = record["chapter_id"]
    from label_pipeline import chapter_source

    text, from_epub = chapter_source(con, chapter_id)
    if record.get("text_sha256") and record["text_sha256"] != text_hash(text):
        raise StaleLabels(f"Chapter {record['chapter']}: the text changed since it was labelled; relabel it.")
    segments = segment_chunk(text)
    if record.get("segments") not in (None, len(segments)):
        raise StaleLabels(f"Chapter {record['chapter']}: {record['segments']} labelled segments, "
                          f"{len(segments)} now; relabel it.")
    if from_epub:
        replace_chunks(con, chapter_id)  # restore paragraphs an older parser dropped
    lines = build_lines(segments, record["labels"], voices, record.get("labeller", "labeller"))
    sm.save_diarized_lines(chapter_id, lines)
    return len(lines)
