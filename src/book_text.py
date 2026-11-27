"""
The book's text, straight from the EPUB.

Volumes 8 and 9 were seeded by an older parser that silently dropped short
paragraphs: measured 2026-11-25, 2,561 of 16,592 paragraphs (vol 8) and 2,825 of
21,338 (vol 9) were missing from the stored chunks, including ~1,470 lines of
dialogue ("«Yes, He is.»", "He sighed."). Every label next to a missing line is set
up to fail, and the audio skips the words. This module re-reads a chapter from its
EPUB with the current parser, measures what the stored copy lost, and replaces the
stored chunks so labelling always starts from the complete text.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
EPUB_DIR = ROOT / "data" / "input"


@lru_cache(maxsize=4)
def epub_paragraphs(epub_name: str) -> "dict[str, list[str]]":
    """Chapter title -> its paragraphs, in spine order (first occurrence wins)."""
    import ebooklib
    from ebooklib import epub
    from epub_parser import _strip_html

    path = EPUB_DIR / epub_name
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}")
    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    chapters: dict[str, list[str]] = {}
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        title, paragraphs = _strip_html(item.get_content())
        if paragraphs and title not in chapters:
            chapters[title] = paragraphs
    return chapters


def chapter_paragraphs(con: sqlite3.Connection, chapter_id: int) -> "list[str]":
    """The complete paragraphs of one stored chapter, read from its EPUB."""
    row = con.execute(
        "select c.title, p.source_epub from chapters c join projects p on p.id = c.project_id where c.id = ?",
        (chapter_id,)).fetchone()
    if row is None:
        raise ValueError(f"No chapter with id={chapter_id}")
    title, epub_name = row
    paragraphs = epub_paragraphs(epub_name).get(title)
    if paragraphs is None:
        raise LookupError(f"Chapter {title!r} is not in {epub_name}")
    return paragraphs


def chapter_text(con: sqlite3.Connection, chapter_id: int) -> str:
    """Paragraphs joined the way chunks store them ('\\n\\n')."""
    return "\n\n".join(chapter_paragraphs(con, chapter_id))


def _norm(text: str) -> str:
    return " ".join(text.split())


def missing_paragraphs(con: sqlite3.Connection, chapter_id: int) -> "list[str]":
    """Paragraphs of the EPUB chapter that the stored chunks do not contain."""
    stored = _norm(" ".join(r[0] for r in con.execute(
        "select text from chunks where chapter_id = ? order by chunk_index", (chapter_id,))))
    lost = []
    for paragraph in chapter_paragraphs(con, chapter_id):
        probe = _norm(paragraph)[:60]
        if probe and probe not in stored:
            lost.append(paragraph)
    return lost


def replace_chunks(con: sqlite3.Connection, chapter_id: int) -> int:
    """Store the complete chapter text as its chunks. Returns the chunk count.

    Lines are left alone: they are rebuilt from the new chunks when the chapter
    is relabelled, and the chapter keeps playing its old audio until then.
    """
    from epub_parser import CHUNK_MAX_WORDS, _build_chunks, _load_spacy

    paragraphs = chapter_paragraphs(con, chapter_id)
    # spaCy is only needed to split an oversized paragraph; loading it costs seconds.
    needs_nlp = any(len(p.split()) > CHUNK_MAX_WORDS for p in paragraphs)
    chunks = _build_chunks(paragraphs, _load_spacy() if needs_nlp else None)
    with con:
        con.execute("delete from chunks where chapter_id = ?", (chapter_id,))
        con.executemany(
            "insert into chunks (chapter_id, chunk_index, text, word_count) values (?, ?, ?, ?)",
            [(chapter_id, c.chunk_index, c.text, c.word_count) for c in chunks])
        con.execute("update chapters set total_chunks = ? where id = ?", (len(chunks), chapter_id))
    return len(chunks)
