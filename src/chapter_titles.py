"""Real chapter numbers, clean titles and file names from messy EPUB headings.

The EPUB numbers its entries by position, not by chapter: "Chapter 1994  Call to Arms" is
the 141st entry of volume 9, and every volume ends with a contents page titled after the
entry count ("Chapter 422": "Content from Chapter 1841 ... eBook from 9Kafe"). Headings also
vary: "Chapter 1841: Evil Minds", "Chapter: 2232 Cold Front", "Chapter '2362 Hunter and Prey".
This module turns any of them into one identity, so the database, the UI, file names and
tags all agree with the book.
"""

from dataclasses import dataclass
import re

BOOK_TITLE = "Shadow Slave"

_HEADING = re.compile(r"""^\s*chapter\s*[:.'’"\-–—]*\s*(\d{1,5})\b\s*[:.\-–—]*\s*(.*?)\s*$""", re.I)
_BARE_NUMBER = re.compile(r"^\s*(\d{3,5})\s*[:.\-–—]?\s+(\S.*?)\s*$")
_BACK_MATTER = re.compile(r"(?i)^\s*(content from chapter\b|table of contents\b)|ebook from \S+")
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class ChapterIdentity:
    kind: str            # "chapter" (story), "front" (synopsis page) or "back" (contents/credits page)
    number: "int | None"
    name: str            # "Call to Arms"
    display: str         # "Chapter 1994: Call to Arms"


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip(" .:-–—'’\"")


def identify(title, first_text="", book_title=BOOK_TITLE):
    """Classify an EPUB entry and recover its real chapter number and name."""
    title = title or ""
    if _BACK_MATTER.search((first_text or "")[:300]):
        return ChapterIdentity("back", None, "Contents", "Contents (not narrated)")
    match = _HEADING.match(title) or _BARE_NUMBER.match(title)
    if match:
        number, name = int(match.group(1)), _clean(match.group(2))
        return ChapterIdentity("chapter", number, name, f"Chapter {number}: {name}" if name else f"Chapter {number}")
    if _clean(title).casefold() == book_title.casefold():
        return ChapterIdentity("front", None, "Synopsis", "Synopsis")
    name = _clean(title) or "Untitled"
    return ChapterIdentity("chapter", None, name, name)


def strip_leaked_heading(text, identity):
    """Drop a first paragraph that only repeats the chapter heading ("2882 Angels in the Marble").

    Some entries carry their heading inside the text, so the narrator would read it while
    most chapters don't. Returns the text unchanged when the first paragraph is prose.
    """
    if identity.kind != "chapter" or identity.number is None or not text:
        return text
    first, _, rest = text.lstrip().partition("\n")
    words = lambda s: re.findall(r"[a-z0-9]+", s.casefold())
    heading = words(first)
    expected = words(f"{identity.number} {identity.name}")
    if heading and len(heading) <= len(expected) + 1 and heading[-len(expected):] == expected:
        return rest.lstrip("\n")
    return text


def is_heading_line(text, identity):
    """True when a line is only the chapter heading ("Chapter 1852: Champions of Valor")."""
    return bool(text and text.strip()) and strip_leaked_heading(text.strip(), identity) == ""


def safe_name(text, limit=120):
    cleaned = _ILLEGAL.sub(" ", text).strip().rstrip(". ")
    return re.sub(r"\s+", " ", cleaned)[:limit].rstrip(". ") or "Untitled"


def book_folder(project_name, book_title=BOOK_TITLE):
    """'9kafe.com-shadow-slave-vol9-c1841-c2260' -> 'Shadow Slave, Volume 9'; others keep their name."""
    volume = re.search(r"(?i)vol(?:ume)?[ ._-]*(\d+)", project_name or "")
    return safe_name(f"{book_title}, Volume {int(volume.group(1))}" if volume else (project_name or book_title))


def chapter_filename(identity, extension):
    """'1994 - Call to Arms.mp3': sorts in book order and matches the chapter's real number."""
    if identity.number is not None:
        stem = f"{identity.number:04d} - {identity.name}" if identity.name else f"{identity.number:04d}"
    else:
        stem = f"0000 - {identity.display}" if identity.kind == "front" else identity.display
    return f"{safe_name(stem)}.{extension.lstrip('.')}"
