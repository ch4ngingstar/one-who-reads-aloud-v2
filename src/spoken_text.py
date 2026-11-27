"""Spoken-text preparation shared by all audiobook renderers."""

import re


def spoken_reading(source: str, override: str | None, pronunciations: dict) -> str:
    readings = {name.casefold(): value for name, value in pronunciations.items()}
    text = override or source
    if readings:
        names = "|".join(re.escape(name) for name in sorted(readings, key=len, reverse=True))
        text = re.sub(r"(?<!\w)(?:" + names + r")(?!\w)",
                      lambda m: readings[m[0].casefold()], text, flags=re.I)
    return normalize_text(text)

# Non-speech stage directions the LLM occasionally emits inside asterisks.
# These are deleted; any other *emphasised* text keeps its content.
_STAGE_DIRECTION_RE = re.compile(
    r'\*(?:sighs?|pauses?|laughs?|chuckles?|giggles?|groans?|grunts?|gasps?|'
    r'coughs?|snorts?|scoffs?|hums?|exhales?|inhales?|sniffs?|sobs?|'
    r'clears throat|beat|silence)\*',
    re.IGNORECASE,
)

# The EPUB contains these two hostnames spliced into paragraphs with Cyrillic
# lookalikes and changing separators. Match the domain only, never book prose.
_DOMAIN_SEP = r"[.~/`\\_|-]"
_SOURCE_STAMP = re.compile(
    rf"(?<!\w)l[iі]ght{_DOMAIN_SEP}*n[oо]v[eе]l{_DOMAIN_SEP}*"
    rf"(?:w[oо]rld|[cс][aа]v[eе]){_DOMAIN_SEP}+[cс]{_DOMAIN_SEP}*[oо]{_DOMAIN_SEP}*m(?!\w)\.?",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """
    Clean up text for maximum TTS accuracy.
    Fixes Unicode typography, normalises whitespace, and handles
    common novel formatting that confuses speech synthesisers.
    """
    text = _SOURCE_STAMP.sub("", text)
    # Confirmed misspellings in the imported text of Missing Catalyst.
    for error, reading in (("chuckded", "chuckled"), ("noisilly", "noisily")):
        text = re.sub(r"\b" + error + r"\b", reading, text)
    # Unicode quotes → ASCII
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    # Strip italic/emphasis markers but keep their content. Only a known
    # vocabulary of LLM stage directions is removed outright — a generic
    # "any lowercase word" rule would delete legitimately emphasised words
    # like *enormous* from the narration.
    text = _STAGE_DIRECTION_RE.sub('', text)                  # *sighs* → gone
    text = re.sub(r'\*([^*]{1,120})\*', r'\1', text)          # *inner thought* → inner thought
    # Strip square brackets but KEEP their content (e.g. [Aspect of the Void]).
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)
    # Em-dash handling: mid-word interruption → ellipsis; mid-sentence → comma
    text = re.sub(r'(\w)—$', r'\1...', text)
    text = re.sub(r'(\w)—(\w)', r'\1, \2', text)
    text = text.replace('—', ', ')
    # En-dash → spaced hyphen
    text = text.replace('–', ' - ')
    # Horizontal ellipsis → three dots
    text = text.replace('…', '...')
    # Non-breaking space → regular space
    text = text.replace(' ', ' ')
    # Strip zero-width chars
    text = text.replace('​', '').replace('﻿', '')
    # Abbreviations (before punctuation normalization)
    for _pat, _rep in [
        (r'\bDr\.', 'Doctor'), (r'\bMr\.', 'Mister'), (r'\bMrs\.', 'Missus'),
        (r'\bMs\.', 'Miss'), (r'\bSt\.', 'Saint'), (r'\bvs\.', 'versus'),
        (r'\bapprox\.', 'approximately'), (r'\betc\.', 'and so on'),
    ]:
        text = re.sub(_pat, _rep, text)

    # Ordinal numbers
    for _abbr, _word in [
        ('1st','first'),('2nd','second'),('3rd','third'),('4th','fourth'),
        ('5th','fifth'),('6th','sixth'),('7th','seventh'),('8th','eighth'),
        ('9th','ninth'),('10th','tenth'),('11th','eleventh'),('12th','twelfth'),
    ]:
        text = re.sub(r'\b' + re.escape(_abbr) + r'\b', _word, text, flags=re.IGNORECASE)

    # Symbols
    text = re.sub(r'(\d+)\s*%', r'\1 percent', text)
    text = re.sub(r'\$(\d+)', r'\1 dollars', text)

    # Collapse multiple spaces / dangling punctuation from stripped markers
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'[,;]\s*$', '.', text)
    text = re.sub(r'(\w)$', lambda m: m.group(1) + '.', text)
    return text.strip()


def split_for_speech(text: str, max_chars: int) -> list:
    """Split text at sentence boundaries when it exceeds max_chars.
    A single sentence longer than max_chars is hard-split at the last
    comma (or space) before the limit so no segment can overflow."""
    if len(text) <= max_chars:
        return [text]

    def hard_split(sent: str) -> list:
        parts = []
        while len(sent) > max_chars:
            cut = sent.rfind(',', max_chars // 2, max_chars)
            if cut != -1:
                head, sent = sent[:cut + 1], sent[cut + 1:]   # keep the comma
            else:
                cut = sent.rfind(' ', max_chars // 2, max_chars)
                if cut != -1:
                    head, sent = sent[:cut], sent[cut + 1:]
                else:
                    head, sent = sent[:max_chars], sent[max_chars:]
            parts.append(head.strip())
            sent = sent.strip()
        if sent:
            parts.append(sent)
        return parts

    units: list = []
    for sent in re.split(r'(?<=[.!?])\s+', text):
        if len(sent) > max_chars:
            units.extend(hard_split(sent))
        else:
            units.append(sent)

    chunks, cur = [], ""
    for unit in units:
        if cur and len(cur) + 1 + len(unit) <= max_chars:
            cur += " " + unit
        else:
            if cur:
                chunks.append(cur)
            cur = unit
    if cur:
        chunks.append(cur)
    return chunks or [text]

