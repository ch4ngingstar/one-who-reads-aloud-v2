"""Transcribe a finished chapter locally and locate passages to check by ear."""

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import _resolve_stored_path
from tts_engine import _normalize_text


def tokens(text):
    return re.findall(r"[\w]+", text.lower().replace("’", "").replace("'", ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter_id", type=int)
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    parser.add_argument("--model", default="base", help="Cached faster-whisper model or directory")
    parser.add_argument("--output", type=Path, help="Optional JSON report with timestamps")
    args = parser.parse_args()
    with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        chapter = conn.execute("SELECT title, output_audio_path FROM chapters WHERE id=?",
                               (args.chapter_id,)).fetchone()
        if not chapter or not chapter[1]:
            parser.error("This chapter has no finished audio")
        rows = conn.execute("SELECT line_index, speaker, text FROM lines WHERE chapter_id=? ORDER BY line_index",
                            (args.chapter_id,)).fetchall()
    expected, line_numbers = [], []
    master = _resolve_stored_path(chapter[1])
    sheet = master.with_suffix(".performance.json")
    spoken = {}
    if sheet.is_file():
        edition = json.loads(sheet.read_text(encoding="utf-8"))
        spoken = {(c["index"], c["source"]): c["spoken"] for c in edition["cues"]}
    for index, speaker, text in rows:
        words = tokens(spoken.get((index, text), _normalize_text(text)))
        expected.extend(words)
        line_numbers.extend([index] * len(words))
    if not expected:
        parser.error("No spoken text is available for comparison")
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", local_files_only=True)
    segments, info = model.transcribe(str(master), language="en",
                                      word_timestamps=True, condition_on_previous_text=False)
    heard, times = [], []
    for segment in segments:
        for word in segment.words or []:
            parts = tokens(word.word)
            heard.extend(parts)
            times.extend([(word.start, word.end)] * len(parts))
    matched, review = 0, []
    for operation, a, b, c, d in SequenceMatcher(None, expected, heard, autojunk=False).get_opcodes():
        if operation == "equal":
            matched += b - a
        elif max(b - a, d - c) >= 3:
            review.append({"line_index": line_numbers[min(a, len(line_numbers) - 1)],
                           "at_seconds": round(times[c][0] if c < len(times) else info.duration, 2),
                           "expected": " ".join(expected[a:b]), "heard": " ".join(heard[c:d])})
    report = {"chapter": chapter[0], "model": args.model, "source_words": len(expected),
              "matched_words_pct": round(100 * matched / len(expected), 1), "review": review}
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
