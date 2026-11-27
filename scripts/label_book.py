"""Label, double-check and store a range of chapters - one command, safe to re-run.

    python scripts/label_book.py --from 1841 --to 1850
    python scripts/label_book.py --from 1841 --to 1850 --no-import    # labels only

1. Qwen labels each chapter (data/labels/qwen-v1/).
2. Gemma, a different model family, gives a blind second opinion on every quoted line
   (data/labels/qwen-v1-checked/). Lines where Qwen's votes split or Gemma disagrees are
   flagged for review (measured: unflagged lines 98.4% right on unseen chapters).
3. The chapters are stored: complete EPUB text, speakers, emotions, review flags.

Each step runs in its own process so one model is fully out of VRAM before the next
loads, and each step skips chapters it already finished: after a power cut, run the
same command again.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels" / "qwen-v1"
CHECKED = ROOT / "data" / "labels" / "qwen-v1-checked"


def run(step: str, args: "list[str]") -> None:
    print(f"== {step}", flush=True)
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / args[0]), *args[1:]], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"{step} failed (exit {result.returncode}); fix it and run the same command again.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="first", type=int, required=True)
    parser.add_argument("--to", dest="last", type=int, required=True)
    parser.add_argument("--no-import", action="store_true")
    args = parser.parse_args(argv)
    if args.last < args.first:
        parser.error("--to must not be before --from")
    span = ["--from", str(args.first), "--to", str(args.last)]
    run("Labelling with Qwen", ["relabel.py", *span, "--out", str(LABELS)])
    run("Second opinion from Gemma", ["second_opinion.py", str(LABELS), str(CHECKED)])
    if not args.no_import:
        run("Storing in the database", ["import_labels.py", *span, "--labels", str(CHECKED)])


if __name__ == "__main__":
    main()
