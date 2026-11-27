"""
Deterministic text segmenter (pass 1 of labelling)
===================================================
Splits chunk text into ordered segments BEFORE any labeller sees it, so labellers
only label segments (speaker / kind / emotion) and never reproduce text. Word loss
is structurally impossible: every character of input lands in exactly one
segment, in order (only the quote marks that delimit a span are dropped).

Segment kinds:
  dialogue -- a quoted span opened by a double-quote glyph (" “ ” « »).
  thought  -- a quoted span opened by a single-quote glyph (' ‘ ’). This EPUB
              marks inner monologue with single quotes (italics were stripped).
  system   -- a paragraph made only of [bracket] spans: Nightmare Spell
              notifications, or rune/telepathic messages.
  prose    -- everything else: narration, actions, attribution tails.

Why a scanner and not regex pairing: the source EPUBs (scraped web novel) are
typographically noisy. Measured over volumes 8-11: 1,552 «guillemet» paragraphs,
224 paragraphs that open with one quote style and close with the other ('…" or
"…'), and ~470 paragraphs whose quote never closes (the English convention for a
speech that continues into the next paragraph, or a dropped closing mark). The
old pairing segmenter narrated all of these as prose. The scanner decides by
*position*: an opening mark sits at a word start and is followed by text; a
closing mark follows text and is not followed by a letter. That rule leaves
apostrophes (don't, Sunny's) and plural possessives (the guards' weapons) alone.

When the glyphs cannot settle a span's kind -- mixed styles, «guillemets» (used
for both speech and thought in volume 8), a quote that never closes, a closing
mark with no opener -- the segment carries ``hint`` flags so the labeller makes
the call instead of the glyph.
"""

import re

DOUBLE_QUOTES = '"“”«»'
SINGLE_QUOTES = "'‘’"
_QUOTES = DOUBLE_QUOTES + SINGLE_QUOTES

# A paragraph made only of [bracket] spans (one or more), whitespace, and
# optional stray trailing punctuation ("[X.]." appears in the source).
_SYSTEM_PARA_RE = re.compile(r"^(?:\s*\[[^\[\]]+\]\s*[.…]*)+\s*$")
_BRACKET_SPAN_RE = re.compile(r"\[[^\[\]]+\]")

# Decoration the scraper leaves at paragraph edges ("*...Yes.\"", "«Time to begin.*").
_EDGE_JUNK = "*﻿ \t"

KIND_DIALOGUE = "dialogue"
KIND_THOUGHT = "thought"
KIND_SYSTEM = "system"
KIND_PROSE = "prose"

HINT_MIXED = "mixed-quotes"        # opened with one quote style, closed with the other
HINT_GUILLEMET = "guillemets"      # «» -- speech or thought, the glyph does not say
HINT_UNCLOSED = "unclosed"         # quote runs to the paragraph end without closing
HINT_STRAY_CLOSE = "stray-close"   # paragraph ends with a closing mark it never opened
HINT_FIRST_PERSON = "first-person"  # narration saying "I"/"you": quote marks probably lost
HINT_INLINE_BRACKET = "inline-bracket"  # a [message] standing as its own sentence in narration

# Third-person narration never says "I" or "you" outside quotes; when it does, the quote
# marks were lost (measured: 152 of 54,152 narration segments, mostly real speech).
_FIRST_PERSON = re.compile(r"\b(?:I|I'm|I've|I'll|I'd|me|my|myself|we're|you|you're|your|yourself)\b")
# A [bracketed] sentence after a sentence end, e.g. 'Cassie took a breath. [So... I am dead...]'.
# Ability names sit mid-sentence ('activated [Where is my eye?]') and are not matched.
_INLINE_BRACKET = re.compile(r"(?:^|(?<=[.!?…\"”:]\s))(\[[^\[\]]*\s[^\[\]]*\])(?=\s+[A-Z“\"'‘\[]|\s*$)")


def _glyph_class(ch: str) -> str:
    return "double" if ch in DOUBLE_QUOTES else "single"


def _kind_for(glyph_class: str) -> str:
    return KIND_DIALOGUE if glyph_class == "double" else KIND_THOUGHT


def _can_open(text: str, i: int) -> bool:
    """A quote at ``i`` can open a span: at a word start, followed by text."""
    if text[i] == "»":
        return False
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if not nxt or nxt.isspace():
        return False
    prev = text[i - 1] if i > 0 else ""
    if prev in ".!?" and nxt.isupper():
        return True  # glued to the previous sentence by the scraper: smiled."This
    return not prev or prev.isspace() or prev in "([{—–-:…*"


def _can_close(text: str, i: int) -> bool:
    """A quote at ``i`` can close a span: after text, not followed by a letter."""
    if text[i] in "«‘":
        return False
    prev = text[i - 1] if i > 0 else ""
    if not prev or prev.isspace():
        return False
    nxt = text[i + 1] if i + 1 < len(text) else ""
    return not nxt.isalnum()


def _is_apostrophe(text: str, i: int) -> bool:
    """A single-quote glyph inside a word (don't, Sunny's, rock'n'roll)."""
    prev = text[i - 1] if i > 0 else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    return prev.isalnum() and nxt.isalnum()


def _is_plural_possessive(text: str, i: int) -> bool:
    """``s'`` followed by a lowercase word: the soldiers' camp, not a closing mark."""
    rest = text[i + 1:].lstrip()
    return i > 0 and text[i - 1] in "sS" and rest[:1].islower()


def _closes_later(core: str) -> bool:
    return any(ch in DOUBLE_QUOTES and _can_close(core, i) for i, ch in enumerate(core))


class _Paragraph:
    """Scans one paragraph into (kind, text, hints) parts."""

    def __init__(self, para: str):
        self.core = para.strip(_EDGE_JUNK)
        self.parts: list[tuple[str, str, list[str]]] = []
        self.open_class: "str | None" = None
        self.hints: list[str] = []
        self.start = 0
        if para.lstrip().startswith("*") and self.core[:1].isalnum() and _closes_later(self.core):
            # Some scraped chapters replace the opening quote with "*".
            self.open_class, self.hints = "double", [HINT_STRAY_CLOSE]

    def emit(self, kind: str, text: str, hints: "list[str]") -> None:
        text = text.strip(_EDGE_JUNK)
        if kind != KIND_PROSE:
            # A glyph that did not act as a delimiter ("»Oh, no.") is still not a word.
            text = text.strip(_QUOTES + _EDGE_JUNK)
        if not text:
            return
        if any(c.isalnum() for c in text) or not self.parts:
            self.parts.append((kind, text, list(dict.fromkeys(hints))))
        else:
            # Lone punctuation between spans ("..." / "!") joins the previous part.
            kind0, text0, hints0 = self.parts[-1]
            self.parts[-1] = (kind0, f"{text0} {text}", hints0)

    def scan(self) -> None:
        core = self.core
        for i, ch in enumerate(core):
            if ch not in _QUOTES:
                continue
            cls = _glyph_class(ch)
            if cls == "single" and _is_apostrophe(core, i):
                continue
            if self.open_class is None:
                if _can_open(core, i):
                    self.emit(KIND_PROSE, core[self.start:i], [])
                    self.open_class, self.start = cls, i + 1
                    self.hints = [HINT_GUILLEMET] if ch == "«" else []
                continue
            self._maybe_close(i, cls)
        self._finish()

    def _maybe_close(self, i: int, cls: str) -> None:
        # Inside a span a same-class mark closes it. A mark of the other class
        # closes it only at the paragraph end ('…" corruption); elsewhere it is a
        # nested quotation ("drop the 'teacher' and…") and stays in the text.
        core = self.core
        at_end = not core[i + 1:].strip(_EDGE_JUNK + ".,!?…")
        same = cls == self.open_class
        if not _can_close(core, i) or not (same or at_end):
            return
        if self.open_class == "single" and cls == "single" and not at_end and _is_plural_possessive(core, i):
            return
        hints = self.hints + ([] if same else [HINT_MIXED])
        self.emit(_kind_for(self.open_class), core[self.start:i], hints)
        self.open_class, self.start, self.hints = None, i + 1, []

    def _finish(self) -> None:
        core = self.core
        if self.open_class is not None:
            # A quote that never closes runs to the paragraph end: either a speech
            # continued in the next paragraph (which reopens with its own mark) or
            # a dropped closing mark. Narration never follows inside the paragraph.
            self.emit(_kind_for(self.open_class), core[self.start:], self.hints + [HINT_UNCLOSED])
            return
        tail = core[self.start:].rstrip(_EDGE_JUNK)
        last = len(tail) - 1
        if (not self.parts and tail and tail[-1] in _QUOTES and _can_close(tail, last)
                and not (tail[-1] in SINGLE_QUOTES and last > 0 and tail[last - 1] in "sS")):
            # The paragraph ends with a closing mark it never opened: the opener
            # was lost. Most likely a quote; the labeller confirms the kind.
            self.emit(_kind_for(_glyph_class(tail[-1])), tail[:-1], [HINT_STRAY_CLOSE])
        else:
            self.emit(KIND_PROSE, tail, [])


def segment_chunk(text: str, *, include_paragraph: bool = False) -> "list[dict]":
    """
    Split chunk text into ordered segments for labelling.

    Returns [{"index": int, "kind": str, "text": str}] plus ``"hint": [...]``
    when the quote glyphs left the kind uncertain, and ``"paragraph"`` /
    ``"review_reason"`` when ``include_paragraph`` is set. Paragraphs are
    '\\n\\n'-separated (epub_parser contract). Empty input yields [].
    """
    segments: list[dict] = []

    def add(kind: str, seg_text: str, hints: "list[str]", paragraph_index: int) -> None:
        segment = {"index": len(segments), "kind": kind, "text": seg_text}
        if hints:
            segment["hint"] = hints
        if include_paragraph:
            segment["paragraph"] = paragraph_index
            reason = _review_reason(hints)
            if reason:
                segment["review_reason"] = reason
        segments.append(segment)

    for paragraph_index, para in enumerate(re.split(r"\n\s*\n", text or "")):
        para = para.strip()
        if not para:
            continue
        if _SYSTEM_PARA_RE.match(para):
            for span in _BRACKET_SPAN_RE.findall(para):
                add(KIND_SYSTEM, span, [], paragraph_index)
            continue
        scanner = _Paragraph(para)
        scanner.scan()
        for kind, part_text, hints in scanner.parts:
            if kind != KIND_PROSE:
                add(kind, part_text, hints, paragraph_index)
                continue
            for sub_kind, sub_text, sub_hints in _split_prose(part_text):
                add(sub_kind, sub_text, sub_hints, paragraph_index)

    return segments


def _split_prose(text: str) -> "list[tuple[str, str, list[str]]]":
    """Narration, with stand-alone [messages] split out and lost-quote suspects flagged."""
    parts, cursor = [], 0
    for match in _INLINE_BRACKET.finditer(text):
        parts.append((KIND_PROSE, text[cursor:match.start()].strip(), []))
        parts.append((KIND_SYSTEM, match.group(1), [HINT_INLINE_BRACKET]))
        cursor = match.end()
    parts.append((KIND_PROSE, text[cursor:].strip(), []))
    out = []
    for kind, part, hints in parts:
        if not part:
            continue
        # Ability names in brackets ("[Where is my eye?]") are not the narrator saying "my".
        if kind == KIND_PROSE and _FIRST_PERSON.search(_BRACKET_SPAN_RE.sub("", part)):
            hints = [HINT_FIRST_PERSON]
        out.append((kind, part, hints))
    return out


def _review_reason(hints: "list[str]") -> "str | None":
    if HINT_UNCLOSED in hints:
        return "Check the quote boundary. The closing quote is missing."
    if HINT_STRAY_CLOSE in hints:
        return "Check the quote boundary. The opening quote is missing."
    if HINT_MIXED in hints:
        return "Check speech or thought. The quote marks disagree."
    return None


def needs_kind_decision(segment: dict) -> bool:
    """True when the glyphs could not settle speech vs thought vs narration."""
    return bool(segment.get("hint"))
