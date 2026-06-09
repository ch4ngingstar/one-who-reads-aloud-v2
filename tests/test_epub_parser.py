"""
Test suite for Module 1: epub_parser.py
Run: python tests/test_epub_parser.py
"""

import json
import sys
import zipfile
import tempfile
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from epub_parser import (
    ParsedBook, Chapter, TextChunk,
    _strip_html, _build_chunks, parse_epub,
    CHUNK_TARGET_WORDS, CHUNK_MAX_WORDS,
)


# ── Minimal fake spaCy nlp for tests (no model download needed) ──────────────
class _FakeSent:
    def __init__(self, text): self.text = text

class _FakeDoc:
    def __init__(self, text):
        import re
        self._sents = [_FakeSent(s.strip()) for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    @property
    def sents(self): return iter(self._sents)

class FakeNLP:
    def __call__(self, text): return _FakeDoc(text)


NLP = FakeNLP()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_strip_html_extracts_title_and_paragraphs():
    html = b"""
    <html><body>
      <h1>Chapter 1: The Dream</h1>
      <p>Sunny woke up covered in cold sweat.</p>
      <p>The nightmare had been vivid, almost real.</p>
    </body></html>
    """
    title, paras = _strip_html(html)
    assert title == "Chapter 1: The Dream", f"Got: {title}"
    assert len(paras) == 2
    assert "Sunny" in paras[0]
    print("  PASS test_strip_html_extracts_title_and_paragraphs")


def test_strip_html_removes_scripts():
    html = b"""
    <html><body>
      <script>alert('xss')</script>
      <p>Valid paragraph with enough text to pass the length filter.</p>
    </body></html>
    """
    _, paras = _strip_html(html)
    for p in paras:
        assert "alert" not in p
    print("  PASS test_strip_html_removes_scripts")


def test_chunker_respects_word_limit():
    # 60 paragraphs of ~10 words each = 600 words total
    paragraphs = [f"This is sentence number {i} in the test paragraph." for i in range(60)]
    chunks = _build_chunks(paragraphs, NLP)
    for chunk in chunks:
        assert chunk.word_count <= CHUNK_MAX_WORDS, (
            f"Chunk {chunk.chunk_index} exceeded max: {chunk.word_count} words"
        )
    print(f"  PASS test_chunker_respects_word_limit ({len(chunks)} chunks from 60 paragraphs)")


def test_chunker_no_empty_chunks():
    paragraphs = ["Hello world, this is a test." for _ in range(10)]
    chunks = _build_chunks(paragraphs, NLP)
    for chunk in chunks:
        assert chunk.text.strip(), "Empty chunk found"
        assert chunk.word_count > 0
    print("  PASS test_chunker_no_empty_chunks")


def test_chunker_preserves_all_text():
    paragraphs = [f"Paragraph {i}: The darkness was absolute and the echo refused to respond." for i in range(20)]
    original_words = sum(len(p.split()) for p in paragraphs)
    chunks = _build_chunks(paragraphs, NLP)
    chunked_words = sum(c.word_count for c in chunks)
    # Word counts can differ slightly due to join whitespace — check text content
    combined = " ".join(c.text for c in chunks)
    for para in paragraphs:
        core = para.split(":")[1].strip()
        assert core in combined, f"Text lost: '{core}'"
    print(f"  PASS test_chunker_preserves_all_text ({original_words} -> {chunked_words} words)")


def test_output_json_schema():
    """Create a minimal fake EPUB and verify the JSON output matches the contract."""
    # Build a minimal valid EPUB zip in memory
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    with zipfile.ZipFile(tmp_path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
        zf.writestr("OEBPS/content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="uid">test-123</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="ch1"/>
  </spine>
</package>""")
        zf.writestr("OEBPS/toc.ncx", """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="test-123"/></head>
  <docTitle><text>Test Book</text></docTitle>
  <navMap></navMap>
</ncx>""")
        chapter_html = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <h1>Chapter One: First Light</h1>
  <p>Sunny opened his eyes and stared at the cracked ceiling of his apartment.</p>
  <p>He had dreamed of the Nightmare Creature again, its hollow eyes boring into his soul.</p>
  <p>The Spell had chosen him. Of all the worthless, ordinary people in the world, it had chosen him.</p>
</body>
</html>"""
        zf.writestr("OEBPS/chapter1.xhtml", chapter_html)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_json:
        json_path = Path(tmp_json.name)

    try:
        result = parse_epub(tmp_path, json_path)

        # Verify dataclass structure
        assert isinstance(result, ParsedBook)
        assert result.total_chapters >= 1
        assert len(result.chapters) == result.total_chapters

        ch = result.chapters[0]
        assert isinstance(ch, Chapter)
        assert ch.chapter_index == 0
        assert "First Light" in ch.title
        assert len(ch.chunks) >= 1

        chunk = ch.chunks[0]
        assert isinstance(chunk, TextChunk)
        assert chunk.chunk_index == 0
        assert len(chunk.text) > 0
        assert chunk.word_count > 0

        # Verify JSON file matches contract
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)

        assert "source_epub" in data
        assert "total_chapters" in data
        assert "chapters" in data
        assert data["chapters"][0]["chunks"][0]["word_count"] > 0

        print("  PASS test_output_json_schema")
    finally:
        import gc
        gc.collect()   # release ebooklib's ZipFile handle before Windows lets us delete
        try:
            tmp_path.unlink(missing_ok=True)
        except PermissionError:
            pass        # Windows may still hold lock; file will be cleaned by OS on exit
        json_path.unlink(missing_ok=True)


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_strip_html_extracts_title_and_paragraphs,
    test_strip_html_removes_scripts,
    test_chunker_respects_word_limit,
    test_chunker_no_empty_chunks,
    test_chunker_preserves_all_text,
    test_output_json_schema,
]

if __name__ == "__main__":
    print("Running Module 1 tests...\n")
    passed, failed = 0, 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
