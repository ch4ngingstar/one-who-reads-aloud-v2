"""The labelling steps shared by the app's Start button and the command-line scripts.

1. ``label_record``       Qwen labels one chapter (speaker, kind, emotion per quote).
2. ``add_second_opinion`` Gemma, a different model family, votes blind on every quote.
3. ``label_import.import_chapter`` stores the result, flagging lines the two disagree on.

Measured on chapters never used for tuning: lines where Qwen's two blind votes and
Gemma agree were 98.4% right; the rest (about 1 in 10 quotes) are flagged for review.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import time

from attribution_evidence import gather
from book_text import chapter_paragraphs, chapter_text
from character_bible import Bible
import label_prompts as P
from segmenter import segment_chunk

ROOT = Path(__file__).resolve().parents[1]
GEMMA = ROOT / "models" / "google_gemma-3-12b-it-Q4_K_M.gguf"
TAIL_PARAGRAPHS = 14


def chapter_source(con: sqlite3.Connection, chapter_id: int) -> "tuple[str, bool]":
    """(text, from_epub). The EPUB is the complete text; books whose EPUB is not in
    data/input (demo scenes, older imports) fall back to the stored chunks."""
    try:
        return chapter_text(con, chapter_id), True
    except (LookupError, FileNotFoundError):
        rows = con.execute("select text from chunks where chapter_id = ? order by chunk_index", (chapter_id,))
        text = "\n\n".join(r[0] for r in rows)
        if not text.strip():
            raise LookupError(f"Chapter {chapter_id} has no text to label")
        return text, False


def previous_tail(con: sqlite3.Connection, chapter_id: int) -> "list[str]":
    """The last paragraphs of the chapter before, so a scene that carries over keeps its speakers."""
    row = con.execute("select project_id, chapter_index from chapters where id = ?", (chapter_id,)).fetchone()
    if not row:
        return []
    before = con.execute("select id from chapters where project_id = ? and chapter_index = ? and kind = 'chapter'",
                         (row[0], row[1] - 1)).fetchone()
    if not before:
        return []
    try:
        return chapter_paragraphs(con, before[0])[-TAIL_PARAGRAPHS:]
    except (LookupError, FileNotFoundError):
        return []


def label_record(labeller, con: sqlite3.Connection, chapter_id: int) -> dict:
    """Label one chapter with Qwen. Returns the record the scripts save as JSON."""
    from label_import import text_hash
    from qwen_labeller import LABELLER_VERSION

    number, title = con.execute("select chapter_number, coalesce(display_title, title) from chapters where id = ?",
                                (chapter_id,)).fetchone()
    started = time.time()
    text, from_epub = chapter_source(con, chapter_id)
    segments = segment_chunk(text, include_paragraph=True)
    labels = labeller.label_chapter(segments, title, previous_tail(con, chapter_id) if from_epub else [])
    return {"chapter": number, "chapter_id": chapter_id, "title": title, "labeller": LABELLER_VERSION,
            "labelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - started, 1), "segments": len(segments),
            "text_sha256": text_hash(text), "labels": labels}


class Gemma:
    """Gemma 3 instruct via llama-cpp-python. Gemma has no system role: the rules lead the turn."""

    def __init__(self, path: Path = GEMMA, n_ctx: int = 12288):
        from llama_cpp import Llama, LlamaGrammar
        if not Path(path).exists():
            raise FileNotFoundError(f"Second-opinion model not found: {path}")
        self.llm = Llama(model_path=str(path), n_gpu_layers=-1, n_ctx=n_ctx, n_batch=1024,
                         flash_attn=True, type_k=8, type_v=8, verbose=False)
        self.n_ctx, self._grammar, self._grammars = n_ctx, LlamaGrammar, {}

    def choose(self, system: str, user: str, choices: str) -> "str | None":
        prompt = f"<start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n<start_of_turn>model\n"
        tokens = self.llm.tokenize(prompt.encode("utf-8"), add_bos=True, special=True)
        if len(tokens) + 2 >= self.n_ctx:
            return None
        if choices not in self._grammars:
            self._grammars[choices] = self._grammar.from_string(
                "root ::= " + " | ".join(f'"{c}"' for c in choices), verbose=False)
        out = self.llm.create_completion(tokens, max_tokens=1, temperature=0.0, grammar=self._grammars[choices])
        answer = out["choices"][0]["text"].strip()
        return answer if answer in choices else None

    def close(self) -> None:
        self.llm.close()


def add_second_opinion(gemma: Gemma, bible: Bible, con: sqlite3.Connection, record: dict) -> dict:
    """Give every quoted line a blind Gemma vote (``label['gemma']``) over Qwen's candidates."""
    text, _ = chapter_source(con, record["chapter_id"])
    segments = segment_chunk(text, include_paragraph=True)
    evidence = gather(bible, segments)
    system = P.system_prompt(bible)
    chapter = P.render_chapter(segments, record["title"], [])
    by_index = {s["index"]: s for s in segments}
    for label in record["labels"]:
        if label["kind"] not in ("speech", "thought", "telepathy") or not label.get("options"):
            continue
        order = list(reversed(label["options"][:-1])) + ["@other"]
        question = P.speaker_question(by_index[label["index"]], evidence[label["index"]], bible, order, [],
                                      thought=label["kind"] == "thought")
        choices = P.letters(len(order))
        letter = gemma.choose(system, chapter + "\n\n" + question, choices)
        label["gemma"] = order[choices.index(letter)] if letter else None
    return record
