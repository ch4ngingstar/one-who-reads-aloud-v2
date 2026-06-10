"""
Module 1: EPUB Parser + Text Chunker
======================================
INPUT:  Path to a .epub file
OUTPUT: ParsedBook dataclass / JSON file

Output JSON Contract (consumed by Module 2 - State Manager):
{
  "source_epub": str,          # original filename
  "total_chapters": int,
  "chapters": [
    {
      "chapter_index": int,    # 0-based
      "title": str,
      "chunks": [
        {
          "chunk_index": int,  # 0-based within chapter
          "text": str,         # plain text, paragraph breaks = \\n\\n
          "word_count": int
        }
      ]
    }
  ]
}
"""

import re
import json
import sys
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import spacy


# ── Chunking constants ────────────────────────────────────────────────────────
# Target keeps LLM prompts comfortably within context window
CHUNK_TARGET_WORDS = 500
CHUNK_MAX_WORDS    = 650

# Document titles that indicate navigation/boilerplate — skip these
_SKIP_PATTERN = re.compile(
    r"(table of contents|copyright|dedication|about the author|\btoc\b|\bnav\b)",
    re.IGNORECASE,
)


# ── Data contracts ────────────────────────────────────────────────────────────

@dataclass
class TextChunk:
    chunk_index: int
    text: str
    word_count: int


@dataclass
class Chapter:
    chapter_index: int
    title: str
    chunks: list = field(default_factory=list)   # list[TextChunk]


@dataclass
class ParsedBook:
    source_epub: str
    total_chapters: int
    chapters: list = field(default_factory=list) # list[Chapter]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_spacy():
    try:
        return spacy.load("en_core_web_sm", disable=["ner", "tagger", "lemmatizer"])
    except OSError:
        raise RuntimeError(
            "\n[parser] spaCy model not found.\n"
            "Run: python -m spacy download en_core_web_sm"
        )


def _strip_html(html_bytes: bytes) -> tuple[str, list[str]]:
    """Return (title, [paragraph_strings]) from raw HTML document bytes."""
    soup = BeautifulSoup(html_bytes.decode("utf-8", errors="replace"), "html.parser")

    # Title: first heading tag wins
    title = ""
    for tag in soup.find_all(["h1", "h2", "h3"]):
        candidate = tag.get_text(strip=True)
        if candidate:
            title = candidate
            break

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "aside", "footer", "header"]):
        tag.decompose()

    paragraphs = []
    for p in soup.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text(separator=" ", strip=True))
        # Keep anything containing letters — short dramatic lines ("No.",
        # "Run!") are real story content. Drop only decorative separators
        # (***, ---, ◆◆◆) and empty paragraphs.
        if text and re.search(r"[A-Za-z]", text):
            paragraphs.append(text)

    return title, paragraphs


def _sentences_from(paragraph: str, nlp) -> list[str]:
    """Tokenize a single paragraph into sentences."""
    return [s.text.strip() for s in nlp(paragraph).sents if s.text.strip()]


def _build_chunks(paragraphs: list[str], nlp) -> list[TextChunk]:
    """
    Pack paragraphs into word-bounded chunks.
    Never breaks mid-sentence. Oversized paragraphs are split at
    sentence boundaries before packing.
    """
    # Flatten paragraphs into atomic units (sentence groups <= MAX_WORDS)
    units: list[str] = []
    for para in paragraphs:
        if len(para.split()) <= CHUNK_MAX_WORDS:
            units.append(para)
        else:
            # Split oversized paragraph at sentence boundaries
            sentences = _sentences_from(para, nlp)
            bucket, bucket_wc = [], 0
            for sent in sentences:
                swc = len(sent.split())
                if bucket_wc + swc > CHUNK_MAX_WORDS and bucket:
                    units.append(" ".join(bucket))
                    bucket, bucket_wc = [sent], swc
                else:
                    bucket.append(sent)
                    bucket_wc += swc
            if bucket:
                units.append(" ".join(bucket))

    # Pack units into chunks targeting CHUNK_TARGET_WORDS
    chunks: list[TextChunk] = []
    buffer: list[str] = []
    buffer_wc = 0
    chunk_idx = 0

    for unit in units:
        unit_wc = len(unit.split())
        if buffer_wc + unit_wc > CHUNK_TARGET_WORDS and buffer:
            chunks.append(TextChunk(chunk_idx, "\n\n".join(buffer), buffer_wc))
            chunk_idx += 1
            buffer, buffer_wc = [], 0
        buffer.append(unit)
        buffer_wc += unit_wc

    if buffer:
        chunks.append(TextChunk(chunk_idx, "\n\n".join(buffer), buffer_wc))

    return chunks


# ── Public API ────────────────────────────────────────────────────────────────

def parse_epub(
    epub_path: "str | Path",
    output_json: "Optional[str | Path]" = None,
) -> ParsedBook:
    """
    Parse an EPUB into structured chapters with sentence-safe text chunks.

    Args:
        epub_path:   Path to the .epub file.
        output_json: Optional path to write the result as JSON.

    Returns:
        ParsedBook dataclass matching the output contract above.
    """
    epub_path = Path(epub_path)
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB not found: {epub_path}")

    print(f"[parser] Loading: {epub_path.name}")
    book = epub.read_epub(str(epub_path))
    nlp  = _load_spacy()

    chapters: list[Chapter] = []
    chapter_idx = 0

    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        title, paragraphs = _strip_html(item.get_content())

        if not paragraphs:
            continue
        if title and _SKIP_PATTERN.search(title):
            print(f"[parser] Skipping boilerplate: '{title[:60]}'")
            continue

        if not title:
            title = f"Chapter {chapter_idx + 1}"

        chunks = _build_chunks(paragraphs, nlp)
        if not chunks:
            continue

        chapters.append(Chapter(chapter_index=chapter_idx, title=title, chunks=chunks))
        chapter_idx += 1
        print(
            f"[parser] [{chapter_idx:>4}] '{title[:55]:<55}' "
            f"-> {len(chunks)} chunk(s), "
            f"~{sum(c.word_count for c in chunks)} words"
        )

    parsed = ParsedBook(
        source_epub=epub_path.name,
        total_chapters=len(chapters),
        chapters=chapters,
    )

    if output_json:
        out_path = Path(output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(asdict(parsed), fh, ensure_ascii=False, indent=2)
        print(f"[parser] Saved -> {out_path}")

    print(f"\n[parser] Complete: {parsed.total_chapters} chapters parsed.")
    return parsed


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python epub_parser.py <book.epub> [output.json]")
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else "data/parsed/book.json"
    parse_epub(sys.argv[1], out)
