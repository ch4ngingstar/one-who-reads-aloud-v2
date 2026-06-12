"""
Deterministic text segmenter (pass 1 of the two-pass diarizer)
==============================================================
Splits chunk text into ordered segments BEFORE the LLM sees it, so the LLM
only labels segments (speaker + emotion) and never reproduces text. Word loss
is structurally impossible: every character of input lands in exactly one
segment, in order.

Segment kinds:
  dialogue -- a double-quoted span (straight "..." or curly “...”), with the
              outer quote marks stripped.
  thought  -- a 'single-quoted' span: this EPUB marks inner monologue with
              single quotes (italics were stripped at parse time). Outer quote
              marks stripped. Only spans at word boundaries qualify, so
              apostrophes/contractions/possessives never trigger a split.
  system   -- a [bracketed] Nightmare Spell notification. Only paragraphs that
              consist entirely of bracket spans (with optional trailing
              punctuation) qualify; inline refs like [Silver Bell] mid-sentence
              stay inside prose.
  prose    -- everything else: narration, actions, attribution tails.

Robustness rules:
  * A paragraph with an unbalanced double quote falls back to one prose
    segment -- never guess at span boundaries.
  * Thought spans tolerate internal contractions (I'll, won't, Sunny's).
"""

import re

# Straight double quotes pair with straight, curly with curly.
_QUOTE_PAIRS = {'"': '"', "“": "”"}  # " -> ",  “ -> ”

# A paragraph made only of [bracket] spans (one or more), whitespace, and
# optional stray trailing punctuation ("[X.]." appears in the source).
_SYSTEM_PARA_RE = re.compile(r"^(?:\s*\[[^\[\]]+\]\s*[.…]*)+\s*$")
_BRACKET_SPAN_RE = re.compile(r"\[[^\[\]]+\]")

# A 'single-quoted' inner-monologue span. The opener must sit at a word
# boundary and the closer must be followed by whitespace/punctuation/end, so
# contractions (I'll, won't) and possessives (Sunny's, guards') never match.
# Interior apostrophes are allowed only when followed by a word character.
_THOUGHT_SPAN_RE = re.compile(
    r"(?:(?<=\s)|^)(['‘])"            # opener at word boundary
    r"((?:[^'’]|['’](?=\w))+?)"       # interior; apostrophes only in contractions
    r"['’](?=[\s.,!?;:)\]]|$)"        # closer at word boundary
)

KIND_DIALOGUE = "dialogue"
KIND_THOUGHT = "thought"
KIND_SYSTEM = "system"
KIND_PROSE = "prose"


def _split_quoted_paragraph(para: str) -> "list[tuple[str, str]]":
    """
    Split one paragraph into (kind, text) parts on double-quote spans.
    Returns the whole paragraph as a single prose part when any quote is
    unbalanced, so no text is ever lost or misattached.
    """
    parts: list[tuple[str, str]] = []
    buf_start = 0
    i = 0
    n = len(para)
    while i < n:
        ch = para[i]
        if ch in _QUOTE_PAIRS:
            closer = _QUOTE_PAIRS[ch]
            end = para.find(closer, i + 1)
            if end == -1:
                # Unbalanced quote -> whole paragraph is prose.
                return [(KIND_PROSE, para.strip())] if para.strip() else []
            before = para[buf_start:i].strip()
            if before:
                parts.append((KIND_PROSE, before))
            spoken = para[i + 1 : end].strip()
            if spoken:
                parts.append((KIND_DIALOGUE, spoken))
            i = end + 1
            buf_start = i
        else:
            i += 1
    tail = para[buf_start:].strip()
    if tail:
        parts.append((KIND_PROSE, tail))
    return parts


def _split_thought_parts(text: str) -> "list[tuple[str, str]]":
    """Split a prose part on 'single-quoted' inner-monologue spans."""
    parts: list[tuple[str, str]] = []
    pos = 0
    for m in _THOUGHT_SPAN_RE.finditer(text):
        before = text[pos : m.start()].strip()
        if before:
            parts.append((KIND_PROSE, before))
        inner = m.group(2).strip()
        if inner:
            parts.append((KIND_THOUGHT, inner))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        parts.append((KIND_PROSE, tail))
    return parts


def segment_chunk(text: str) -> "list[dict]":
    """
    Split chunk text into ordered segments for LLM labeling.

    Returns [{"index": int, "kind": "dialogue"|"system"|"prose", "text": str}].
    Paragraphs are '\\n\\n'-separated (epub_parser contract). Empty input
    yields an empty list.
    """
    segments: list[dict] = []

    def add(kind: str, seg_text: str) -> None:
        segments.append({"index": len(segments), "kind": kind, "text": seg_text})

    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue

        if _SYSTEM_PARA_RE.match(para):
            for span in _BRACKET_SPAN_RE.findall(para):
                add(KIND_SYSTEM, span)
            continue

        for kind, part_text in _split_quoted_paragraph(para):
            if kind == KIND_PROSE:
                for sub_kind, sub_text in _split_thought_parts(part_text):
                    add(sub_kind, sub_text)
            else:
                add(kind, part_text)

    return segments
