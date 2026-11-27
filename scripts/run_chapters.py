"""Render a chapter range from the command line with the same cast settings as the studio."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    from installed_models import installed_models
    choices = installed_models(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=int, help="First chapter index (zero based)")
    parser.add_argument("end", nargs="?", type=int, help="Last chapter index (inclusive)")
    parser.add_argument("--epub", default="9kafe.com-shadow-slave-vol9-c1841-c2260.epub",
                        help="Existing book filename or the path to an EPUB to import")
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    parser.add_argument("--llm", default=next(iter(choices["llm"]), None))
    parser.add_argument("--tts", default=choices["tts"][0]["path"] if choices["tts"] else None)
    args = parser.parse_args()
    end = args.end if args.end is not None else args.start
    if args.start < 0 or end < args.start:
        parser.error("Choose a nonnegative, ascending chapter range.")
    if not args.llm or not args.tts:
        parser.error("Install a director and a speech renderer, or provide --llm and --tts.")
    if os.name == "nt":
        import torch
        os.environ["PATH"] = str(Path(torch.__file__).parent / "lib") + os.pathsep + os.environ["PATH"]
    from orchestrator import PipelineConfig, PipelineOrchestrator
    cfg = PipelineConfig(epub_path=args.epub, llm_model_path=args.llm, tts_model_dir=args.tts,
                         db_path=str(args.db), audio_wav_dir=str(ROOT / "data/audio"),
                         audio_mp3_dir=str(ROOT / "data/output"), log_path=str(ROOT / "data/pipeline.log"),
                         chapter_range=(args.start, end))
    result = PipelineOrchestrator(cfg).run()
    print(result)
    return int(result["error"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
