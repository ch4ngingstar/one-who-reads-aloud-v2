"""Render one imported chapter in isolation and measure cold wall time and audio length."""

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orchestrator import PipelineConfig, PipelineOrchestrator
from state_manager import StateManager, _resolve_stored_path
from gpu_measurement import GpuMemory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapter_id", type=int, help="Database chapter ID")
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    parser.add_argument("--tts", type=Path, default=ROOT / "profiles/full-cast.json")
    parser.add_argument("--llm", type=Path, default=ROOT / "models/Qwen3-14B-Q4_K_M.gguf")
    parser.add_argument("--reuse-labels", action="store_true", help="Time speech and assembly only")
    parser.add_argument("--voice", action="append", default=[], metavar="SPEAKER=FILE",
                        help="Audition a reference in this benchmark only")
    args = parser.parse_args()
    with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        chapter = source.execute("SELECT title FROM chapters WHERE id=?", (args.chapter_id,)).fetchone()
        if not chapter:
            parser.error("Unknown chapter ID")
        chunks = [dict(row) for row in source.execute(
            "SELECT chunk_index, text, word_count FROM chunks WHERE chapter_id=? ORDER BY chunk_index",
            (args.chapter_id,))]
        voices = dict(source.execute("SELECT speaker, ref_audio_path FROM voices"))
        readings = {}
        if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pronunciations'").fetchone():
            readings = dict(source.execute("SELECT spelling, reading FROM pronunciations"))
        labels = source.execute("SELECT * FROM lines WHERE chapter_id=? ORDER BY line_index",
                                (args.chapter_id,)).fetchall()
    if args.reuse_labels and not labels:
        parser.error("This chapter has no saved labels")
    for override in args.voice:
        speaker, sep, path = override.partition("=")
        if not sep or not Path(path).is_file():
            parser.error(f"Expected SPEAKER=FILE, got {override!r}")
        voices[speaker] = str(Path(path).resolve())
    parent = ROOT / "data/benchmarks"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"ch-{args.chapter_id}-", dir=parent))
    config = PipelineConfig(epub_path="benchmark.epub", db_path=str(output / "benchmark.db"),
                            tts_model_dir=str(args.tts.resolve()), llm_model_path=str(args.llm.resolve()),
                            audio_wav_dir=str(output / "lines"), audio_mp3_dir=str(output),
                            log_path=str(output / "run.log"), cleanup_wavs=False)
    sm = StateManager(config.db_path)
    project = sm.seed_project({"source_epub": config.epub_path, "total_chapters": 1,
                               "chapters": [{"chapter_index": 0, "title": chapter["title"], "chunks": chunks}]})
    cid = sm.get_all_chapters(project)[0]["id"]
    for speaker, path in voices.items():
        sm.set_voice(speaker, str(_resolve_stored_path(path)))
    for spelling, reading in readings.items():
        sm.set_pronunciation(spelling, reading)
    if args.reuse_labels:
        sm.save_diarized_lines(cid, [dict(row) for row in labels])
    print(f"Benchmark directory: {output}", flush=True)
    start = time.perf_counter()
    pipeline = PipelineOrchestrator(config)
    with GpuMemory() as gpu:
        result = pipeline.run()
    elapsed = time.perf_counter() - start
    rendered = sm.get_chapter_by_id(cid)
    if result["success"] != 1:
        sys.exit(rendered["error_message"] or "Benchmark failed")
    audio = rendered["output_audio_path"]
    seconds = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio
    ], text=True).strip())
    sheet = json.loads(Path(audio).with_suffix(".performance.json").read_text("utf-8"))
    cues = sheet["cues"]
    if [cue["index"] for cue in cues] != [row["line_index"] for row in sm.get_lines_for_chapter(cid)]:
        sys.exit("Master cue order does not match the saved script")
    if any(c["end_ms"] <= c["start_ms"] or (i and c["start_ms"] < cues[i-1]["end_ms"])
           for i, c in enumerate(cues)) or abs(seconds - sheet["duration_ms"] / 1000) > 0.5:
        sys.exit("Timed script does not match the recorded chapter duration")
    character_seconds = sum((c["end_ms"] - c["start_ms"]) / 1000 for c in cues if c["actor"] != "Narrator")
    report = {"chapter": chapter["title"], "words": sum(c["word_count"] for c in chunks),
              "lines": rendered["total_lines"], "tts": config.tts_model_dir, "audio": audio,
              "llm": config.llm_model_path, **gpu.report(),
              "within_forty_minutes": elapsed <= 2400, "character_seconds": round(character_seconds, 2),
              "cache_hits": sum(bool(c["cached"]) for c in cues),
              "retakes": sum(bool(c["audit"].get("retake")) for c in cues),
              "flagged_lines": [c["index"] for c in cues if c["audit"].get("review") or c["fallback"]],
              "stages": [{k: v for k, v in event.items() if k in ("type", "model", "stage", "elapsed_s")}
                         for event in pipeline.events if event["type"] in ("stage_done", "model_load", "vram_barrier")],
              "reused_labels": args.reuse_labels, "wall_seconds": round(elapsed, 2),
              "audio_seconds": seconds, "real_time_factor": round(elapsed / seconds, 3)}
    (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
