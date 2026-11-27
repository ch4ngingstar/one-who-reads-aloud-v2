"""Who needs a voice: rank speakers and gather what the novel says about how they sound.

Labelled chapters give exact line counts per speaker. Unlabelled volumes (the post-2300
books) are estimated from the raw text: a paragraph that contains a quotation is credited
to a name that attributes it ("…," Jet said / Jet asked: "…" / Jet frowned. "…").
Gender comes from the pronouns that follow a name; voice evidence from sentences such as
"Aether's voice was quiet and reserved". The output feeds voice briefs and casting rounds;
it never changes the cast by itself.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import re
import sqlite3

from casting import alias_chain

SPEECH_VERBS = (
    "said|asked|replied|answered|whispered|muttered|shouted|yelled|called|added|continued|"
    "explained|insisted|demanded|growled|hissed|snapped|sighed|murmured|remarked|declared|"
    "announced|interjected|retorted|repeated|chuckled|laughed|smiled|grinned|scoffed|frowned|"
    "nodded|shrugged|hesitated|spoke|uttered|drawled|mused|commented|exclaimed|groaned|grumbled"
)
QUOTE = r"[\"“”]"
NAME = r"((?:[A-Z][a-z]+)(?:\s(?:of\s)?[A-Z][a-z]+){0,2})"
_TAIL = re.compile(QUOTE + r"[^\"“”]{2,400}?[,.!?…—]" + QUOTE + r"\s+" + NAME + r"\s+(?:" + SPEECH_VERBS + r")\b")
_TAIL_INVERTED = re.compile(QUOTE + r"[^\"“”]{2,400}?[,.!?…—]" + QUOTE + r"\s+(?:" + SPEECH_VERBS + r")\s+" + NAME)
_LEAD = re.compile(r"(?:^|[.!?]\s+)" + NAME + r"\s+(?:" + SPEECH_VERBS + r")\b[^\"“”]{0,80}?[:,]?\s*" + QUOTE)
_PRONOUN = re.compile(r"\b(he|him|his|she|her|hers)\b", re.I)

# Capitalised words that open sentences or are titles, not speakers.
STOPWORDS = {
    "He", "She", "They", "It", "I", "We", "You", "The", "His", "Her", "Their", "Then", "But", "And",
    "After", "Finally", "Still", "Eventually", "Instead", "Suddenly", "Soon", "Now", "Here", "There",
    "This", "That", "What", "When", "Where", "Why", "How", "Who", "Which", "Someone", "Somebody",
    "Everyone", "Nobody", "Saint", "Lord", "Lady", "Sir", "Master", "King", "Queen", "Prince",
    "Princess", "Sovereign", "Detective", "Captain", "Commander", "Chief", "Doctor", "Mister", "Miss",
    "Another", "One", "Two", "Three", "All", "Some", "Both", "Each", "Even", "Only", "Just", "Yet",
    "Of", "In", "At", "On", "As", "So", "Well", "Yes", "No", "Oh", "Ah", "Hm", "Hmm", "Ugh",
}


def canonical(name):
    return alias_chain(re.sub(r"\s+", " ", name).strip().title())[-1]


def _chapter_number(title):
    found = re.search(r"(\d{3,5})", title or "")
    return int(found.group(1)) if found else None


@dataclass
class Speaker:
    name: str
    lines_labelled: int = 0
    est_dialogue: int = 0
    chapters: set = field(default_factory=set)
    he: int = 0
    she: int = 0
    voiced: bool = False
    evidence: list = field(default_factory=list)
    quotes: list = field(default_factory=list)

    @property
    def gender(self):
        if self.he + self.she < 4:
            return "unknown"
        share = self.she / (self.he + self.she)
        return "female" if share >= 0.65 else "male" if share <= 0.35 else "unknown"

    def as_dict(self):
        return {"name": self.name, "lines_labelled": self.lines_labelled, "est_dialogue": self.est_dialogue,
                "chapters": len(self.chapters), "first_chapter": min(self.chapters, default=None),
                "gender": self.gender, "voiced": self.voiced, "evidence": self.evidence}


def _paragraphs(con, project_ids, min_chapter):
    marks = ",".join("?" * len(project_ids))
    rows = con.execute(f"select c.title, k.text from chunks k join chapters c on c.id = k.chapter_id "
                       f"where c.project_id in ({marks}) order by c.project_id, c.chapter_index, k.chunk_index",
                       list(project_ids))
    for title, text in rows:
        number = _chapter_number(title)
        if number is None or (min_chapter and number < min_chapter):
            continue
        for paragraph in re.split(r"\n\s*\n", text):
            yield number, paragraph


_SUBJECT = re.compile(r"^(?:[A-Z][a-z]+ing [^,]{0,60},\s*)?" + NAME + r"(?:'s|’s)?\b")


def _beat_subject(paragraph):
    """The named subject of a paragraph's last sentence: "Nephis remained silent, then sighed." -> Nephis."""
    sentence = re.split(r"(?<=[.!?:])\s+", paragraph.strip())[-1]
    found = _SUBJECT.match(sentence)
    if found and found.group(1).split()[0] not in STOPWORDS:
        return found.group(1)
    return None


def _credit(paragraph, previous, history):
    """Names credited with the quotation in `paragraph` (this EPUB puts beats before quotes)."""
    credited = set()
    for pattern in (_TAIL, _TAIL_INVERTED, _LEAD):
        credited.update(m.group(1) for m in pattern.finditer(paragraph))
    credited = {raw for raw in credited if raw.split()[0] not in STOPWORDS}
    if credited or not paragraph.lstrip()[:1] in "\"“":
        return credited
    if previous is not None and not re.match(r"\s*" + QUOTE, previous):
        subject = _beat_subject(previous)
        return {subject} if subject else set()
    # Back-and-forth exchange: the speaker before the last one answers again.
    if len(history) >= 2 and history[-1] != history[-2]:
        return {history[-2]}
    return set()


_QUOTED = re.compile("[\"“]([^\"“”]{8,300})[\"”]")
_MID_SENTENCE = re.compile(r"(?<=[a-z,;] )([A-Z][a-z]+)")


def proper_nouns(paragraphs, minimum=3):
    """Words the book capitalises mid-sentence: names, not sentence openers like "However"."""
    counts = {}
    for _, paragraph in paragraphs:
        for word in _MID_SENTENCE.findall(paragraph):
            counts[word] = counts.get(word, 0) + 1
    return {word for word, n in counts.items() if n >= minimum}


def speaker_estimates(con, project_ids, min_chapter=None, name_min=3):
    """Credit quoted paragraphs to the names that attribute them; count pronouns per name."""
    stats = {}
    paragraphs = list(_paragraphs(con, project_ids, min_chapter))
    # name_min=0 disables the proper-noun filter (tiny texts cannot show mid-sentence use).
    names = proper_nouns(paragraphs, name_min) if name_min else None
    previous, history, chapter = None, [], None
    for number, paragraph in paragraphs:
        if number != chapter:
            previous, history, chapter = None, [], number
        if re.search(QUOTE, paragraph):
            for raw in _credit(paragraph, previous, history):
                if names is not None and raw.split()[0] not in names:
                    continue
                name = canonical(raw)
                speaker = stats.setdefault(name, Speaker(name))
                speaker.est_dialogue += 1
                speaker.chapters.add(number)
                history.append(name)
                if len(speaker.quotes) < 60:
                    speaker.quotes.extend((number, q.strip()) for q in _QUOTED.findall(paragraph))
        previous = paragraph
    # Gender: the first pronouns after each mention of a credited name.
    firsts = {name.split()[0]: speaker for name, speaker in stats.items()}
    mention = re.compile(r"\b(" + "|".join(re.escape(f) for f in firsts) + r")\b") if firsts else None
    for _, paragraph in paragraphs if mention else ():
        for found in mention.finditer(paragraph):
            for pronoun in _PRONOUN.findall(paragraph[found.end():found.end() + 120])[:2]:
                speaker = firsts[found.group(1)]
                if pronoun.lower() in ("he", "him", "his"):
                    speaker.he += 1
                else:
                    speaker.she += 1
    return stats


def audition_quotes(stats, name, count=2, min_words=6, max_words=26):
    """Quotations credited to `name`, of a comfortable audition length, spread across chapters."""
    speaker = stats.get(name)
    if speaker is None:
        return []
    chosen, seen_chapters = [], set()
    for number, quote in speaker.quotes:
        words = len(quote.split())
        if min_words <= words <= max_words and number not in seen_chapters and not re.search(r"[\[\]<>]", quote):
            chosen.append({"chapter": number, "text": quote})
            seen_chapters.add(number)
            if len(chosen) == count:
                break
    return chosen


def voice_evidence(con, project_ids, name, limit=6):
    """Sentences that describe how `name` sounds ("…Aether's voice was quiet and reserved…")."""
    first = name.split()[0]
    sentence = re.compile(r"[^.!?\n]*\b" + re.escape(first) + r"\b[^.!?\n]*")
    found = []
    for _, paragraph in _paragraphs(con, project_ids, None):
        if first not in paragraph:
            continue
        for candidate in sentence.findall(paragraph):
            if re.search(r"\bvoice\b|\btone\b", candidate, re.I):
                cleaned = re.sub(r"\s+", " ", candidate).strip()
                if 20 <= len(cleaned) <= 220 and cleaned not in found:
                    found.append(cleaned)
                    if len(found) >= limit:
                        return found
    return found


def discover(db, project_ids, min_chapter=None, top=40, evidence=True):
    """Rank speakers for the given projects: labelled counts where labels exist, estimates elsewhere."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    voices = {key.casefold() for (key,) in con.execute("select speaker from voices")}
    stats = speaker_estimates(con, project_ids, min_chapter)
    marks = ",".join("?" * len(project_ids))
    for speaker, count in con.execute(f"select l.speaker, count(*) from lines l join chapters c on c.id = l.chapter_id "
                                      f"where c.project_id in ({marks}) group by l.speaker", list(project_ids)):
        name = canonical(speaker)
        stats.setdefault(name, Speaker(name)).lines_labelled += count
    ranked = sorted(stats.values(), key=lambda s: s.lines_labelled + 2 * s.est_dialogue, reverse=True)
    ranked = [s for s in ranked if s.name not in ("Narrator", "_default", "Unknown")][:top]
    for speaker in ranked:
        speaker.voiced = any(key.casefold() in voices for key in alias_chain(speaker.name))
        if evidence and not speaker.voiced:
            speaker.evidence = voice_evidence(con, project_ids, speaker.name)
    return [s.as_dict() for s in ranked]
