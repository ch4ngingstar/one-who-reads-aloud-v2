"""Who can speak: canonical names, genders and every name the text uses for them.

Backed by profiles/characters.json. The labeller answers with canonical names; the
evidence layer uses aliases to find characters in narration and genders to resolve
"she said:" to the right person.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BIBLE_PATH = ROOT / "profiles" / "characters.json"

NARRATOR = "Narrator"
SPELL = "The Nightmare Spell"
UNNAMED_PREFIX = "Unnamed"


@dataclass
class Bible:
    genders: dict[str, str]
    aliases: dict[str, str]                      # lowercased alias -> canonical
    notes: "dict[str, str]" = field(default_factory=dict)        # shown to the labeller
    often_with: "dict[str, list[str]]" = field(default_factory=dict)  # hidden companions
    # Descriptions that mean one character only in another's scenes: "her teacher" is
    # Sunny wherever Rain is (268 of 278 uses in volumes 8-11). phrase -> (canonical, condition)
    descriptors: "dict[str, tuple[str, str]]" = field(default_factory=dict)
    active: "dict[str, str]" = field(default_factory=dict)  # phrase -> canonical, this chapter
    _pattern: "re.Pattern | None" = field(default=None, repr=False)

    @classmethod
    def load(cls, path: Path = BIBLE_PATH) -> "Bible":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            characters = data["characters"]
        except (OSError, ValueError, KeyError) as error:
            raise ValueError(f"Unreadable character sheet {path}: {error}") from error
        genders, aliases, notes, often_with, descriptors = {}, {}, {}, {}, {}
        for name, info in characters.items():
            for phrase, condition in info.get("descriptors", {}).items():
                descriptors[phrase.lower()] = (name, condition)
            gender = info.get("gender", "unknown")
            if gender not in ("male", "female", "unknown"):
                raise ValueError(f"{name}: gender must be male, female or unknown, not {gender!r}")
            genders[name] = gender
            for alias in [name, *info.get("aliases", [])]:
                aliases.setdefault(alias.lower(), name)
            if info.get("notes"):
                notes[name] = info["notes"]
            if info.get("often_with"):
                often_with[name] = list(info["often_with"])
        return cls(genders, aliases, notes, often_with, descriptors)

    def activate(self, present: "list[str] | set[str]") -> None:
        """Switch on the descriptions that apply with these characters in the chapter."""
        self.active = {phrase: who for phrase, (who, condition) in self.descriptors.items()
                       if condition in present}

    def closest(self, name: str) -> "str | None":
        """A known character this is a likely misspelling of ('Lustern' -> Luster, 'Ajko' -> Aiko).

        The source text has OCR-style typos; short names need a near-exact match so that
        two real names (Kim, Kai) are never merged."""
        import difflib
        key = name.lower()
        if len(key) < 3:
            return None
        cutoff = 0.66 if len(key) == 3 else 0.75
        found = difflib.get_close_matches(key, list(self.aliases), n=3, cutoff=cutoff)
        # Swapped letters ("Rani") are the commonest typo: an anagram beats an equal score (Roan).
        anagram = [a for a in found if sorted(a) == sorted(key)]
        best = (anagram or found or [None])[0]
        return self.aliases[best] if best else None

    def in_alias(self, word: str) -> bool:
        """True when ``word`` is part of a longer known alias ('Fallen' in 'Song of the Fallen')."""
        word = word.lower()
        return any(word in alias.split() for alias in self.aliases if " " in alias)

    def resolve_description(self, description: str) -> "str | None":
        """A canonical name hidden in a free description ('young lady Tamar' -> Tamar)."""
        text = description.title() if description.islower() else description
        # "Ling's father" describes someone else: a possessive name is never the person.
        found = [(pos, name) for pos, name in self.mentions(text)
                 if not re.match(r"\S*['’]s?\s", text[pos:] + " ", re.I)]
        return found[0][1] if found else self.canonical(description)

    def canonical(self, name: str) -> "str | None":
        """Canonical name for any alias, ignoring a leading 'the'; None when unknown."""
        key = " ".join(name.split()).lower()
        return self.aliases.get(key) or self.aliases.get(key.removeprefix("the ").strip())

    def gender(self, name: str) -> str:
        canonical = self.canonical(name) or name
        return self.genders.get(canonical, "unknown")

    @property
    def names(self) -> "list[str]":
        return list(self.genders)

    def mention_pattern(self) -> "re.Pattern":
        """Matches any alias as a whole word; longest alias first so 'King of Swords' beats 'King'."""
        if self._pattern is None:
            alts = sorted(self.aliases, key=len, reverse=True)
            body = "|".join(re.escape(a) for a in alts if not a.startswith("the "))
            self._pattern = re.compile(r"(?<![\w'’])(?:" + body + r")(?![\w])", re.I)
        return self._pattern

    def mentions(self, text: str) -> "list[tuple[int, str]]":
        """(position, canonical) for every character named in ``text``.

        Case matters for single-word aliases ("Star", "Rain", "Light" are also
        ordinary words): only capitalised occurrences count.
        """
        found = []
        for match in self.mention_pattern().finditer(text):
            raw = match.group(0)
            if not raw[0].isupper():
                continue
            canonical = self.canonical(raw)
            if canonical:
                found.append((match.start(), canonical))
        for phrase, who in self.active.items():
            found += [(m.start(), who) for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", text, re.I)]
        return sorted(found)


def is_unnamed(speaker: str) -> bool:
    return speaker.startswith(UNNAMED_PREFIX)
