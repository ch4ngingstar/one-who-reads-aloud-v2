"""Measure director attribution against source-reviewed scenes using scratch databases."""
import argparse
from collections import Counter
from importlib.util import find_spec
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if os.name == "nt":
    # llama.cpp needs the CUDA DLLs bundled with PyTorch, not its Python runtime.
    torch_spec = find_spec("torch")
    if torch_spec and torch_spec.origin:
        torch_lib = Path(torch_spec.origin).parent / "lib"
        os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ["PATH"]
        if torch_lib.is_dir():
            _torch_dll_directory = os.add_dll_directory(str(torch_lib))
from llm_director import LLMDirector, DEFAULT_SPEAKERS
from state_manager import StateManager
from segmenter import segment_chunk


FIXTURES = [
    ('Cassie asked, "Sunny, can you hear me?"\n\n"Yes," Sunny replied. "Where are you?"\n\n"Behind you," said Cassie.',
     ["Cassie", "Sunny", "Sunny", "Cassie"]),
    ('"Wait," Nephis said.\n\nEffie looked at her. "For what?"\n\n"For me," said Sunny.\n\n"I can wait," Effie answered.',
     ["Nephis", "Effie", "Sunny", "Effie"]),
    ('Kai turned to Jet. "You heard it too?"\n\nJet nodded. "Twice."\n\nKai lowered his voice. "Then we should go."',
     ["Kai", "Jet", "Kai"]),
]

def gold_indices(gold_labels, segments):
    """Resolve frozen labels to source cues before loading either model."""
    by_text = {}
    for index, segment in enumerate(segments):
        by_text.setdefault(segment["text"], []).append(index)
    seen = set()
    indices = []
    for gold in gold_labels:
        text = gold["text"]
        if "sha256" in gold and sha256(text.encode("utf-8")).hexdigest() != gold["sha256"]:
            raise ValueError(f"Gold text hash does not match {text!r}")
        matches = by_text.get(text, [])
        if "line_index" in gold:
            index = gold["line_index"]
            if type(index) is not int or index not in matches:
                raise ValueError(f"Gold cue {index!r} does not match {text!r}")
        else:
            if len(matches) != 1:
                raise ValueError(f"Expected one source cue for {text!r}; found {len(matches)}. Check the text and provide line_index for repeats.")
            index, = matches
        if index in seen:
            raise ValueError(f"Duplicate gold label for cue {index}")
        seen.add(index)
        indices.append(index)
    return indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    parser.add_argument("--chapter", type=int, default=156)
    parser.add_argument("--gold", type=Path, help="Frozen source-reviewed scene dataset")
    args = parser.parse_args()
    if args.gold:
        scenes = json.loads(args.gold.read_text("utf-8"))["scenes"]
    else:
        with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as db:
            chunks = [row[0] for row in db.execute(
                "SELECT text FROM chunks WHERE chapter_id=? ORDER BY chunk_index", (args.chapter,))]
        if not chunks:
            parser.error("Chapter missing")
        scenes = [{"chapter_id": args.chapter, "split": "real_unlabelled", "chunks": chunks, "gold": []}]
        for index, (text, speakers) in enumerate(FIXTURES):
            speech = [s for s in segment_chunk(text) if s["kind"] == "dialogue"]
            scenes.append({"chapter_id": f"fixture-{index}", "split": "fixtures", "chunks": [text],
                           "gold": [{"text": seg["text"], "line_index": seg["index"], "speaker": speaker}
                                    for seg, speaker in zip(speech, speakers, strict=True)]})
    for scene in scenes:
        scene["segments"] = [s for text in scene["chunks"] for s in segment_chunk(text)]
        try:
            scene["gold_indices"] = gold_indices(scene["gold"], scene["segments"])
        except ValueError as error:
            parser.error(f"Chapter {scene['chapter_id']}: {error}")
    parent = ROOT / "data/benchmarks"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="director-", dir=parent))
    print(output, flush=True)
    sm = StateManager(output / "eval.db")
    project = sm.seed_project({"source_epub": "audit.epub", "total_chapters": len(scenes), "chapters": [
        {"chapter_index": i, "title": str(scene["chapter_id"]), "chunks": [
            {"chunk_index": j, "text": text, "word_count": len(text.split())}
            for j, text in enumerate(scene["chunks"])]} for i, scene in enumerate(scenes)]})
    speakers = sorted(set(DEFAULT_SPEAKERS) | {
        g["speaker"] for scene in scenes for g in scene["gold"] if g["speaker"]})
    results = []
    start = time.monotonic()
    with LLMDirector(args.model, sm, speakers=speakers) as director:
        for scene, chapter in zip(scenes, sm.get_all_chapters(project)):
            director.process_chapter(chapter["id"])
            rows = sm.get_lines_for_chapter(chapter["id"])
            if [r["text"] for r in rows] != [s["text"] for s in scene["segments"]]:
                raise ValueError(f"Directed cues differ from source in chapter {scene['chapter_id']}")
            checks = []
            for gold, index in zip(scene["gold"], scene["gold_indices"], strict=True):
                row = rows[index]
                predicted = row["speaker"]
                checks.append({"line_index": index, "text": gold["text"], "kind": row["kind"],
                               "expected": gold["speaker"], "predicted": predicted,
                               "correct": predicted == gold["speaker"] if gold["speaker"] else None,
                               "gold_evidence": gold.get("evidence"), "attribution": row.get("attribution"),
                               "review_reason": row.get("review_reason")})
            results.append({"chapter_id": scene["chapter_id"], "split": scene["split"],
                            "exact_segment_text": True, "checks": checks})
            print("Completed", scene["chapter_id"], flush=True)
    summary = {}
    for split in sorted({s["split"] for s in scenes}):
        audited = [c for r in results if r["split"] == split for c in r["checks"]]
        checks = [c for c in audited if c["expected"]]
        counts = Counter(c["expected"] for c in checks)
        correct = Counter(c["expected"] for c in checks if c["correct"])
        summary[split] = {"correct": sum(correct.values()), "total": len(checks),
                          "ambiguous_gold": len(audited) - len(checks),
                          "unresolved": sum(c["predicted"] in (None, "Unknown") for c in checks),
                          "macro_actor_accuracy": sum(correct[a] / n for a, n in counts.items()) / len(counts) if counts else None,
                          "by_actor": {a: {"correct": correct[a], "total": n} for a, n in counts.items()}}
    report = {"model": args.model.name, "wall_seconds": round(time.monotonic() - start, 1),
              "dataset": str(args.gold) if args.gold else "fixtures + unlabelled real chapter",
              "summary": summary, "results": results}
    (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": summary, "wall_seconds": report["wall_seconds"]}))


if __name__ == "__main__":
    main()
