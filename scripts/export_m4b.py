"""Package finished chapters into one audiobook file (.m4b) with chapter markers.

    python scripts/export_m4b.py --project 2
    python scripts/export_m4b.py --project 2 --first 1990 --last 1999 --cover cover.jpg

The same export runs from the UI (chapter list -> "Export audiobook"). See src/book_export.py.
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book_export import ExportError, default_output, export  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=int, required=True, help="Project id (see the UI or the projects table)")
    parser.add_argument("--first", type=int, help="First chapter number to include")
    parser.add_argument("--last", type=int, help="Last chapter number to include")
    parser.add_argument("--out", type=Path, help="Output .m4b (default: data/output/books/<album>.m4b)")
    parser.add_argument("--cover", type=Path, help="Cover image (JPEG or PNG) to embed")
    parser.add_argument("--bitrate", default="64k")
    parser.add_argument("--strict", action="store_true", help="Fail if any chapter in range is unfinished")
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db")
    args = parser.parse_args(argv)
    if args.cover and not args.cover.is_file():
        parser.error(f"Cover not found: {args.cover}")
    try:
        out = args.out or default_output(args.db, args.project, ROOT / "data/output/books", args.first, args.last)
        result = export(args.db, args.project, out, args.first, args.last, args.cover, args.bitrate, args.strict)
    except ExportError as exc:
        parser.exit(1, f"{exc}\n")
    print(result)
    return result


if __name__ == "__main__":
    main()
