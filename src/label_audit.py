"""Check speaker labels against what the book itself says, whoever produced the labels.

Measured on volumes 8-9: labels disagreed with an explicit "X said" on 16% of such lines, and
6 of 10 sampled action-beat disagreements were real errors, mostly lines wrongly given to Sunny.
Two kinds of book evidence are collected for each dialogue line:

* explicit: an attribution names the speaker ('"...," Jet said' / 'Nephis asked:');
* beat: the paragraph just before the quote is an action by a named character
  ("Nephis frowned.") - usually the speaker, but not always ("Sunny looked at Nephis.").

Explicit evidence is strong enough to correct a label; beat evidence needs a second opinion.
"""

from collections import defaultdict
import re

from cast_discovery import SPEECH_VERBS, STOPWORDS, canonical

_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z]+)?)"
_TAIL = re.compile(r"^\s*(?:" + SPEECH_VERBS + r")\s+" + _NAME + r"|^\s*" + _NAME + r"\s+(?:" + SPEECH_VERBS + r")\b")
_LEAD = re.compile(_NAME + r"\s+(?:" + SPEECH_VERBS + r")\b[^.!?]{0,80}:\s*$")
_BEAT = re.compile(r"(?:^|[.!?]\s+)" + _NAME + r"(?:'s|’s)?\b[^.!?]*[.!?:]?\s*$")
# A beat that hands the turn to someone else ("Sunny looked at Nephis") is not evidence.
_HANDOFF = re.compile(r"\b(?:looked|glanced|stared|turned|smiled|nodded)\s+(?:at|to|toward|towards)\b", re.I)


def _resolver(roster):
    firsts = {}
    for name in roster:
        firsts.setdefault(name.split()[0], name)

    def who(raw):
        if not raw or raw.split()[0] in STOPWORDS:
            return None
        name = canonical(raw)
        return name if name in roster else firsts.get(raw.split()[0])
    return who


def find_conflicts(lines):
    """lines: dicts with id, chapter_id, line_index, speaker, kind, text (any order).

    Returns dialogue lines whose label disagrees with book evidence, strongest first.
    """
    roster = {canonical(l["speaker"]) for l in lines if l["speaker"] not in ("Narrator", "Unknown", "_default")}
    who = _resolver(roster)
    chapters = defaultdict(list)
    for line in lines:
        chapters[line["chapter_id"]].append(line)
    conflicts = []
    for chapter in chapters.values():
        chapter.sort(key=lambda l: l["line_index"])
        for i, line in enumerate(chapter):
            if line.get("kind") != "dialogue" or line.get("speaker_locked"):
                continue
            before = chapter[i - 1] if i else None
            after = chapter[i + 1] if i + 1 < len(chapter) else None
            evidence, strength = None, None
            if after and after.get("kind") == "prose" and (line["text"].rstrip().endswith(",") or after["text"][:1].islower()):
                found = _TAIL.match(after["text"])
                evidence = who(found and (found.group(1) or found.group(2)))
                strength = "explicit" if evidence else None
            if not evidence and before and before.get("kind") == "prose":
                found = _LEAD.search(before["text"])
                if found:
                    evidence, strength = who(found.group(1)), "explicit"
                else:
                    last = re.split(r"(?<=[.!?])\s+", before["text"].strip())[-1]
                    found = _BEAT.search(last)
                    if found and not _HANDOFF.search(last):
                        evidence, strength = who(found.group(1)), "beat"
            if evidence and evidence != canonical(line["speaker"]):
                context = [l["text"] for l in chapter[max(0, i - 3):i]], line["text"], [l["text"] for l in chapter[i + 1:i + 3]]
                conflicts.append({"line_id": line["id"], "chapter_id": line["chapter_id"], "line_index": line["line_index"],
                                  "label": canonical(line["speaker"]), "evidence": evidence, "strength": strength,
                                  "context": context})
    return sorted(conflicts, key=lambda c: c["strength"] != "explicit")
