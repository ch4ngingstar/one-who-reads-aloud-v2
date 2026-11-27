"""Experiment: an independent second opinion from a different local model family.

    python scripts/second_opinion.py data/labels/test-v1j data/labels/test-v1j-gemma

Qwen's two votes share Qwen's blind spots: when both are wrong they usually agree.
Gemma 3 (Google) reads the same chapter and the same candidate list, blind to Qwen's
answer, so a disagreement exposes lines that look settled but are not. Each quoted
line gets ``gemma`` = Gemma's pick; nothing else changes and the database is untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from attribution_evidence import gather  # noqa: E402
from book_text import chapter_text  # noqa: E402
from character_bible import Bible  # noqa: E402
import label_prompts as P  # noqa: E402
from segmenter import segment_chunk  # noqa: E402

DB = ROOT / "src" / "data" / "pipeline.db"
GEMMA = ROOT / "models" / "google_gemma-3-12b-it-Q4_K_M.gguf"


class Gemma:
    """Gemma 3 instruct via llama-cpp-python. Gemma has no system role: the rules lead the turn."""

    def __init__(self, path: Path = GEMMA, n_ctx: int = 12288):
        from llama_cpp import Llama, LlamaGrammar
        if not path.exists():
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    bible, con = Bible.load(), sqlite3.connect(str(DB))
    system = P.system_prompt(bible)
    model = Gemma()
    try:
        for path in sorted(args.labels.glob("ch_*.json")):
            target = args.out / path.name
            if target.exists():
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            try:
                segments = segment_chunk(chapter_text(con, record["chapter_id"]), include_paragraph=True)
            except LookupError as error:
                print(f"ch {record['chapter']}: SKIPPED - {error}", flush=True)
                continue
            evidence = gather(bible, segments)
            chapter = P.render_chapter(segments, record["title"], [])
            by_index = {s["index"]: s for s in segments}
            for label in record["labels"]:
                if label["kind"] not in ("speech", "thought", "telepathy") or not label.get("options"):
                    continue
                segment = by_index[label["index"]]
                order = list(reversed(label["options"][:-1])) + ["@other"]
                question = P.speaker_question(segment, evidence[label["index"]], bible, order, [],
                                              thought=label["kind"] == "thought")
                letter = model.choose(system, chapter + "\n\n" + question, P.letters(len(order)))
                label["gemma"] = order[P.letters(len(order)).index(letter)] if letter else None
            target.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"ch {record['chapter']} done", flush=True)
    finally:
        model.close()


if __name__ == "__main__":
    main()
