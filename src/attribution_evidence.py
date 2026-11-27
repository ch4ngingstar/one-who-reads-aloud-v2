"""What the text itself says about who speaks each quote.

Measured on the 50-line hand check (2026-11-25) the dominant labelling error was
ignoring a pronoun introduction: 'Finally, she said in an even tone:' followed by
a line labelled with a man. This module reads each quoted segment's surroundings
the way a careful reader does and returns *evidence*, not a verdict:

* tag        -- an attribution names the speaker ('Nephis said:', '"…," said Jet')
* unnamed    -- an attribution describes an unnamed speaker ('one of the porters asked')
* gender     -- an attribution uses a pronoun ('she mumbled:'), with likely antecedents
* beat       -- the speaker's own action right next to the quote ('Nephis frowned. "…"')
* vocatives  -- people addressed inside the quote ("Sunny, wait!") -- the listener
* participants -- characters present in the scene, most recent first

The labeller turns evidence into a short candidate list; validators use it to
catch contradictions. Every rule is deliberately conservative: a missing piece of
evidence costs nothing, a wrong one misleads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from character_bible import Bible, UNNAMED_PREFIX

SPEECH_VERBS = (
    "said|says|asked|asks|replied|answered|whispered|muttered|mumbled|murmured|shouted|yelled|"
    "screamed|cried|called|added|continued|explained|insisted|demanded|growled|hissed|snapped|"
    "sighed|remarked|declared|announced|interjected|retorted|repeated|chuckled|laughed|scoffed|"
    "spoke|uttered|drawled|mused|commented|exclaimed|groaned|grumbled|barked|ordered|commanded|"
    "warned|admitted|agreed|offered|suggested|responded|inquired|noted|stammered|stuttered|"
    "breathed|pleaded|begged|protested|objected|corrected|teased|joked|sneered|roared|wondered|"
    "concluded|confirmed|countered|echoed|grunted|huffed|prompted|questioned|reasoned|recited|"
    "reminded|reported|sang|shrieked|spat|urged|voiced|whimpered|wheezed|chimed in|spoke up|"
    "cut in|piped up|went on|pointed out|called out|blurted out"
)
_VERB = re.compile(r"\b(?:" + SPEECH_VERBS + r")\b", re.I)
_PRONOUN = re.compile(r"\b(he|she)\b", re.I)
_PRONOUN_GENDER = {"he": "male", "she": "female"}
_HANDOFF = re.compile(r"\b(?:looked|glanced|stared|turned|smiled|nodded)\s+(?:at|to|toward|towards)\b", re.I)

# Unnamed speakers: "one of the porters", "the young knight", "a soldier", "the old woman".
_UNNAMED = re.compile(
    r"\b(?:(?:one|some|another|the rest|most|many|a few) of the|the|a|an)\s+((?:[a-z-]+\s+){0,2}?"
    r"(?:porters?|laborers?|labourers?|workers?|villagers?|people|students?|recruits?|citizens?|"
    r"spectators?|onlookers?|refugees?|pilgrims?|nobles?|courtiers?|clerics?|acolytes?|"
    r"soldiers?|knights?|guards?|men|man|women|woman|girl|boy|warriors?|servants?|"
    r"sentr(?:y|ies)|officers?|officials?|clerks?|merchants?|priests?|scouts?|sailors?|"
    r"hunters?|elders?|strangers?|youths?|veterans?|commanders?|captains?|lieutenants?|"
    r"sergeants?|healers?|maids?|attendants?|children|child|kid|lad|lady|gentleman|crowd|"
    r"owners?|hosts?|managers?|businessm[ae]n|shopkeepers?|bartenders?|waiters?|waitress|drivers?|"
    r"receptionists?|doctors?|nurses?|reporters?|employees?|staff|secretar(?:y|ies)|assistants?|"
    r"customers?|clients?|crow|bird|cat|dog|wolf|serpent|snake|horse|beast|creature|"
    r"someone|somebody))\b")
# Unnamed people known only by their relation to someone: "Ling's dad", "her husband".
_KIN = re.compile(r"\b(?:[A-Z][a-z]+(?:'s|’s)|[Hh]is|[Hh]er|[Tt]heir)\s+((?:[a-z]+\s+)?(?:father|dad|mother|mom|"
                  r"husband|wife|son|daughter|brother|sister|uncle|aunt|grandfather|grandmother|grandpa|"
                  r"grandma|friend|servant|guard|bodyguard|subordinate|soldier|assistant|aide|"
                  r"companion|partner|fiancée?|boss|employer|attendant|retainer))\b")
# A capitalised name the character sheet does not know, acting in narration:
# "Old Carel smiled excitedly." / "Crow Crow ... opened its wings".
# Only human gestures and plain speech verbs count: places and powers also "roar" and
# "loom", and a name preceded by "the" ("the Night Garden") is a thing, not a person.
_NEW_NAME = re.compile(r"(?<![Tt]he )\b((?:Old |Young |Little )?[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,})?)\s+"
                       r"(?:said|asked|replied|answered|whispered|muttered|mumbled|added|smiled|nodded|"
                       r"frowned|grinned|laughed|chuckled|giggled|shrugged|sighed|hesitated|glanced|"
                       r"bowed|waved|blinked|scowled|winced|coughed|cawed|remained silent|"
                       r"cleared (?:his|her|its) throat)\b")
_NOT_NAMES = {"The", "He", "She", "They", "It", "His", "Her", "Their", "Then", "But", "And", "When",
              "After", "Before", "Soon", "Suddenly", "Finally", "Eventually", "Still", "Instead", "There",
              "This", "That", "Everyone", "Nobody", "Someone", "Somebody", "One", "Saint", "Lord", "Lady",
              "Master", "King", "Queen", "Prince", "Princess", "Awakened", "Ascended", "Transcendent",
              "Who", "What", "Why", "How", "Where", "Which", "Nothing", "Something", "Everything",
              "Each", "Both", "Many", "Most", "Some", "Several", "None", "Neither", "Either", "All",
              "You", "Dad", "Mom", "People", "Even", "Everywhere", "Legacy", "Fate", "Night", "Heaven",
              "Realm", "Domain", "Knight", "Sleeper", "Wanderer", "Rock", "Terror", "Slayer"}
_FEMALE_KIN = re.compile(r"mother|mom|wife|daughter|sister|aunt|grandmother|grandma|fiancée|waitress", re.I)
_MALE_KIN = re.compile(r"father|dad|husband|son|brother|uncle|grandfather|grandpa|fiancé\b|businessman", re.I)
_FEMALE_NOUNS = re.compile(r"\b(?:women|woman|girl|lady|maids?|queen|princess|mother|sister)\b", re.I)
_MALE_NOUNS = re.compile(r"\b(?:men|man|boy|lad|gentleman|king|prince|father|brother)\b", re.I)

# Capitalised titles used for an unnamed person: "The Master seemed relieved."
_TITLED_UNNAMED = re.compile(r"\b[Tt]he (Master|Saint|Knight|Captain|Commander|Lieutenant|Sergeant|Officer|"
                             r"Elder|Priest|Envoy|Herald|Guard|Instructor|Chief|Administrator)\b(?! [A-Z])")
_SELF_INTRO = re.compile(r"\b(?:I am|I'm|[Mm]y name is|[Cc]all me)\s+((?:[A-Z][a-z]+\s){0,2}[A-Z][a-z]+)(?=[\s.,!?…]|$)")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-Z“\"'‘«])")


@dataclass
class Evidence:
    index: int
    kind: str
    tag: "str | None" = None            # named speaker from an attribution
    tag_source: str = ""                # "tail" | "lead" | "intro"
    unnamed: "str | None" = None        # "Unnamed porter"
    gender: "str | None" = None         # from the attribution (pronoun, name, gendered noun)
    antecedents: "list[str]" = field(default_factory=list)  # pronoun referents, likeliest first
    beat: "str | None" = None           # named subject of an adjacent action beat
    beat_gender: "str | None" = None    # 'She smiled.' right before the quote
    beat_unnamed: "str | None" = None   # 'The Master nodded gratefully.'
    vocatives: "list[str]" = field(default_factory=list)
    participants: "list[str]" = field(default_factory=list)
    same_paragraph_as_previous_quote: bool = False
    follows_quote: "int | None" = None  # previous paragraph was a bare quote: an exchange turn
    groups: "list[str]" = field(default_factory=list)  # unnamed people recently in the narration
    on_stage: "set[str] | None" = None  # named in nearby narration; None = unknown

    @property
    def strong(self) -> "str | None":
        """A speaker the text settles outright, or None."""
        return self.tag or self.unnamed


def _sentences(text: str) -> "list[str]":
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s] or [""]


def _first_person_ref(bible: Bible, text: str) -> "tuple[int, str | None, str | None, str | None]":
    """Earliest reference to a person in ``text``: (position, named, unnamed, gender)."""
    # Relations come first so that at the same position "Ling's dad" / "Her husband" beats
    # the name or pronoun it starts with (min() keeps the first of equal positions).
    candidates = []
    for match in [*_KIN.finditer(text), *_UNNAMED.finditer(text)]:
        role = match.group(1).strip()
        gender = ("female" if _FEMALE_NOUNS.search(role) or _FEMALE_KIN.search(role)
                  else "male" if _MALE_NOUNS.search(role) or _MALE_KIN.search(role) else None)
        candidates.append((match.start(), None, f"{UNNAMED_PREFIX} {role}", gender))
    candidates += [(pos, name, None, bible.gender(name)) for pos, name in bible.mentions(text)]
    candidates += [(m.start(), None, None, _PRONOUN_GENDER[m.group(1).lower()]) for m in _PRONOUN.finditer(text)]
    for match in _TITLED_UNNAMED.finditer(text):
        candidates.append((match.start(), None, f"{UNNAMED_PREFIX} {match.group(1).lower()}", None))
    for match in re.finditer(r"\b(?:[Oo]ne|[Ss]omeone|[Aa]nother) of them\b", text):
        candidates.append((match.start(), None, f"{UNNAMED_PREFIX} member of the group", None))
    if not candidates:
        return -1, None, None, None
    return min(candidates, key=lambda c: c[0])


def _subject(bible: Bible, clause: str) -> "tuple[str | None, str | None, str | None]":
    """(named, unnamed, gender) of whoever speaks in an attribution clause.

    Leading adverbials and participle phrases ("Turning to Sunny, Nephis said") are
    skipped: the subject is looked for after the last comma before the speech verb,
    then from the start of the clause, then after the verb ('…," said Jet').
    """
    verb = _VERB.search(clause)
    before_verb = clause[:verb.start()] if verb else clause
    after_comma = before_verb[before_verb.rfind(",") + 1:]
    for window in (after_comma, before_verb):
        pos, named, unnamed, gender = _first_person_ref(bible, window)
        if pos >= 0:
            return named, unnamed, gender
    if verb:
        _, named, unnamed, gender = _first_person_ref(bible, clause[verb.end():verb.end() + 60])
        return named, unnamed, gender
    return None, None, None


def vocatives(bible: Bible, quote: str) -> "list[str]":
    """Characters addressed by name inside a quote ("Sunny, wait!" / "…, Lady Nephis?")."""
    found = []
    for match in bible.mention_pattern().finditer(quote):
        if not match.group(0)[0].isupper():
            continue
        before = quote[:match.start()].rstrip()
        after = quote[match.end():].lstrip()
        if (not before or before[-1] in ",.!?…—-") and (not after or after[0] in ",.!?…—-"):
            name = bible.canonical(match.group(0))
            if name:
                found.append(name)
    return list(dict.fromkeys(found))


class _Window:
    """Characters seen recently (narration and quote text), most recent first."""

    def __init__(self, bible: Bible, keep: int = 160):
        self.bible, self.keep, self.recent = bible, keep, []

    def see(self, text: str) -> None:
        self.recent.extend(name for _, name in self.bible.mentions(text))
        del self.recent[:-self.keep]

    def participants(self) -> "list[str]":
        return list(dict.fromkeys(reversed(self.recent)))

    def of_gender(self, gender: str, exclude: "set[str]") -> "list[str]":
        return [n for n in self.participants() if self.bible.gender(n) == gender and n not in exclude]


def new_names(bible: Bible, segments: "list[dict]") -> "list[str]":
    """Capitalised names acting in this chapter's narration that the sheet does not know.

    They join the candidate list as themselves ("Carel", "Crow Crow"), so a minor
    named speaker is never forced into "someone else" or onto a cast member."""
    found = []
    for segment in segments:
        if segment["kind"] != "prose":
            continue
        for match in _NEW_NAME.finditer(segment["text"]):
            name = re.sub(r"^(?:Old|Young|Little) ", "", match.group(1))
            if (name.split()[0] in _NOT_NAMES or bible.canonical(name) or bible.canonical(match.group(1))
                    or bible.in_alias(name.split()[0]) or bible.closest(name)
                    or (name.endswith("s") and not name.endswith("ss"))):  # "Saints", "Sovereigns"
                continue  # a known character, a piece of an epithet, or a typo of a known name
            found.append(name)
    return list(dict.fromkeys(found))


def gather(bible: Bible, segments: "list[dict]") -> "dict[int, Evidence]":
    """Evidence for every non-prose segment. Segments should carry ``paragraph`` keys."""
    window = _Window(bible)
    evidence: dict[int, Evidence] = {}
    paragraphs: dict[int, list[dict]] = {}
    for segment in segments:
        paragraphs.setdefault(segment.get("paragraph", segment["index"]), []).append(segment)
    previous_quote_paragraph = None
    # Everyone the chapter names anywhere: a speaker can be named only later
    # ("The man's name was Tegrot"), so the candidate list must look ahead too.
    bible.activate(())
    named_here = {name for s in segments for _, name in bible.mentions(s["text"])}
    bible.activate(named_here)  # e.g. "her teacher" becomes Sunny in Rain's chapters
    whole_chapter = list(dict.fromkeys(name for s in segments for _, name in bible.mentions(s["text"])))
    whole_chapter += new_names(bible, segments)
    # Who the narration shows near each line (30 segments back, 10 ahead). Someone only
    # talked about in dialogue ("Saint Athena's heir") is rarely the one speaking.
    narrated = [[name for _, name in bible.mentions(s["text"])] if s["kind"] == "prose" else []
                for s in segments]

    def on_stage(index: int) -> "set[str]":
        names = {n for found in narrated[max(0, index - 30):index + 11] for n in found}
        return names | {c for n in names for c in bible.often_with.get(n, [])}

    recent_groups: list[str] = []
    for segment in segments:
        if segment["kind"] == "prose" and not segment.get("hint"):
            window.see(segment["text"])
            recent_groups.extend(m.group(1).split()[-1] for m in _UNNAMED.finditer(segment["text"]))
            recent_groups.extend(m.group(0).strip() for m in _KIN.finditer(segment["text"]))
            recent_groups.extend(m.group(1).lower() for m in _TITLED_UNNAMED.finditer(segment["text"]))
            del recent_groups[:-8]
            continue
        paragraph_id = segment.get("paragraph", segment["index"])
        siblings = paragraphs[paragraph_id]
        ev = Evidence(segment["index"], segment["kind"])
        ev.vocatives = vocatives(bible, segment["text"])
        ev.same_paragraph_as_previous_quote = previous_quote_paragraph == paragraph_id
        before = paragraphs.get(paragraph_id - 1, [])
        if (siblings[0] is segment and before and all(s["kind"] != "prose" for s in before)):
            ev.follows_quote = before[-1]["index"]
        _attribution(bible, ev, siblings, siblings.index(segment), paragraphs.get(paragraph_id - 1, []))
        # Narration inside the quote's own paragraph puts its people in scene first.
        for sibling in siblings:
            if sibling["kind"] == "prose":
                window.see(sibling["text"])
        ev.on_stage = on_stage(segments.index(segment))
        ev.groups = [g for g in dict.fromkeys(reversed(recent_groups))
                     if g not in ("someone", "somebody", "voice")][:3]
        intro = _SELF_INTRO.search(segment["text"])
        if intro and not ev.tag:
            words = intro.group(1).split()
            # "I am Awakened Kim": drop leading titles until a known name remains.
            named = next((bible.canonical(" ".join(words[k:])) for k in range(len(words))
                          if bible.canonical(" ".join(words[k:]))), None)
            if named:
                ev.tag, ev.tag_source, ev.gender = named, "self", bible.gender(named)
        if ev.gender and not ev.strong:
            ev.antecedents = window.of_gender(ev.gender, set(ev.vocatives))[:4]
        seen = window.participants()
        companions = [c for name in seen[:6] for c in bible.often_with.get(name, [])]
        ev.participants = list(dict.fromkeys(seen[:12] + companions + whole_chapter))
        evidence[segment["index"]] = ev
        previous_quote_paragraph = paragraph_id
        window.see(segment["text"])
    return evidence


def _attribution(bible: Bible, ev: Evidence, siblings: "list[dict]", position: int,
                 previous_paragraph: "list[dict]") -> None:
    text = siblings[position]["text"].rstrip()
    after = siblings[position + 1] if position + 1 < len(siblings) else None
    before = siblings[position - 1] if position > 0 else None

    # 1. Tail in the same paragraph: '"…," Jet said.' / '"Why?" she asked.' / '"No." Nephis frowned.'
    if after and after["kind"] == "prose":
        first = _sentences(after["text"])[0]
        if (text[-1:] in ",…—-" or first[:1].islower()) and _VERB.search(first[:80]):
            _apply(bible, ev, first, "tail")
            if ev.tag or ev.unnamed or ev.gender:
                return
        pos, named, _, _ = _first_person_ref(bible, first)
        if named and pos == 0:
            ev.beat = named

    # 2. Lead in the same paragraph: 'She said, "…"' / 'Nephis frowned. "…"'
    if before and before["kind"] == "prose":
        last = _sentences(before["text"])[-1].rstrip()
        if last[-1:] in ",:" and (_VERB.search(last) or last.endswith(":")):
            _apply(bible, ev, last, "lead")
            if ev.tag or ev.unnamed or ev.gender:
                return
        pos, named, _, _ = _first_person_ref(bible, last)
        if named and pos >= 0 and not _HANDOFF.search(last):
            ev.beat = ev.beat or named
        return

    # 3. The paragraph before. Ending with ':' it introduces the quote ('Finally, she said
    #    in an even tone:'). Otherwise its last sentence is usually the speaker's own action
    #    ('Morgan laughed.' then Morgan's line) -- this author's commonest way to attribute.
    if position == 0 and previous_paragraph and previous_paragraph[-1]["kind"] == "prose":
        last = _sentences(previous_paragraph[-1]["text"])[-1].rstrip()
        if last.endswith(":"):
            _apply(bible, ev, last, "intro")
            return
        pos, named, unnamed, gender = _first_person_ref(bible, last)
        if pos >= 0 and pos < 40:
            ev.beat = named
            ev.beat_unnamed = unnamed
            ev.beat_gender = gender if not named else bible.gender(named)


def _apply(bible: Bible, ev: Evidence, clause: str, source: str) -> None:
    named, unnamed, gender = _subject(bible, clause)
    if named:
        ev.tag, ev.tag_source, ev.gender = named, source, bible.gender(named)
    elif unnamed:
        ev.unnamed, ev.tag_source, ev.gender = unnamed, source, gender
    elif gender:
        ev.gender, ev.tag_source = gender, source
