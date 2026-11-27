"""Remove scraper watermarks from the book text before anything reads it aloud.

The source EPUBs were scraped from novel sites that inject their names into the
prose, often disguised against filters: "Tʜe sourcᴇ of thɪs content ɪs NoveI~Fire.net",
"n/o/vel/b//in dot c//om", "Join our telegram channel to receive chapters faster".
Measured 2026-11-25 across volumes 8-11: ~50 paragraphs. Left in, the narrator reads
them out (or, glued to a quote, the character does).

Only the injected token and its known lead-in phrase are removed; story text is
never touched.
"""
from __future__ import annotations

import re

# Small-capital look-alikes the injector uses to dodge filters (ʀᴇᴀᴅ ʟᴀᴛᴇsᴛ ...).
_SMALL_CAPS = str.maketrans({"ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ғ": "f", "ɢ": "g",
                             "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n",
                             "ᴏ": "o", "ᴘ": "p", "ʀ": "r", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w",
                             "ʏ": "y", "ᴢ": "z",
                             # Cyrillic look-alikes (lіghtnоvеlworld)
                             "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
                             "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "һ": "h", "ո": "n"})

_SITE = (r"n\W*o\W*v\W*e\W*[lI1]\W*(?:f\W*i\W*r\W*e|b\W*i\W*n)\W*(?:\(\.\)|\.|dot)?\W*"
         r"(?:n\W*e\W*t|c\W*o\W*m)\b")
_LEAD_IN = (r"(?:(?:the\s+)?source\s+of\s+this\s+content\s+is|read\s+latest\s+chapters\s+at|"
            r"this\s+chapter\s+is\s+updated?\s+by|updates\s+are\s+released\s+by|"
            r"content\s+originally\s+comes\s+from|find\s+this\s+and\s+other\s+great\s+novels\s+at)\s*")
_SITE_AT_END = re.compile(_SITE + r"\W*$", re.I)
# Where the injected sentence begins: right after the story's last sentence end.
_LAST_BOUNDARY = re.compile(r".*[.!?…\"”’:]", re.S)
_PATTERNS = [
    re.compile(r"(?:" + _LEAD_IN + r")?" + _SITE, re.I),
    re.compile(r"\bJoin our tele\w* channel to receive chapters faster:?\s*\S*", re.I),
    re.compile(r"\beBook from 9\s*Kafe\b\.?", re.I),
    # "lіght\nоvel\world~c`о/m": letters split by any symbols, Cyrillic folded above.
    re.compile(r"\bl\W*i\W*g\W*h\W*t\W*n\W*o\W*v\W*e\W*l\W*w\W*o\W*r\W*l\W*d\W*c\W*o\W*m\b\.?", re.I),
    re.compile(r"\bBtw, fuck n\S+ b\S+ and r\S+ n\S+", re.I),
]


def scrub(paragraph: str) -> str:
    """The paragraph without injected watermarks; '' when nothing else remains."""
    folded = paragraph.translate(_SMALL_CAPS)  # one character in, one out: positions line up
    at_end = _SITE_AT_END.search(folded)
    if at_end:
        # Watermarks are appended to the paragraph with a varying lead-in ("For more
        # chapters visit", "Official source is"): drop everything after the story's last
        # sentence end. Searching only text before the token keeps that end in the story.
        boundary = _LAST_BOUNDARY.match(folded[:at_end.start()])
        cut = boundary.end() if boundary else 0
        if not re.fullmatch(r"\W*" + r"(?:\w+\W*){0,9}", folded[cut:at_end.start()]):
            cut = at_end.start()  # more than a short lead-in: remove only the token
        paragraph, folded = paragraph[:cut], folded[:cut]
    spans = sorted((m.start(), m.end()) for pattern in _PATTERNS for m in pattern.finditer(folded))
    if not spans:
        return paragraph
    keep, cursor = [], 0
    for start, end in spans:
        if start >= cursor:
            keep.append(paragraph[cursor:start])
        cursor = max(cursor, end)
    keep.append(paragraph[cursor:])
    cleaned = re.sub(r"\s{2,}", " ", "".join(keep)).strip()
    return cleaned if any(ch.isalnum() for ch in cleaned) else ""
