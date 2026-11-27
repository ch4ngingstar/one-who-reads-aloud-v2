"""Register designed voices chosen on the casting page, without touching existing clips.

    python scripts/register_designed_voices.py            # apply profiles/designed-cast.json
    python scripts/register_designed_voices.py --dry-run  # show what would change

Each chosen candidate (data/voice-design/<character>/cand_N.wav + .json) is copied to
src/data/voices/editions/<speaker>-designed.wav with a <same>.txt sidecar holding its exact
script, which OmniVoice uses as the cloning transcript instead of an ASR guess. The speaker is
then pointed at the copy. Re-running is safe: identical copies are left alone, and an edition
file that differs from its source is never overwritten.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager  # noqa: E402

DESIGN = ROOT / "data/voice-design"
EDITIONS = ROOT / "src/data/voices/editions"
CAST = ROOT / "profiles/designed-cast.json"
DB = ROOT / "src/data/pipeline.db"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edition_name(speaker):
    return "-".join(speaker.lower().split()) + "-designed"


def plan(cast):
    steps = []
    for speaker, entry in cast["voices"].items():
        source = DESIGN / (entry["source"] + ".wav")
        meta_path = source.with_suffix(".json")
        if not source.is_file() or not meta_path.is_file():
            raise SystemExit(f"{speaker}: missing designed candidate {source}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha256") and meta["sha256"] != digest(source):
            raise SystemExit(f"{speaker}: {source.name} no longer matches its recorded checksum")
        script = meta["reference_script"].strip()
        if not script:
            raise SystemExit(f"{speaker}: candidate has no reference script")
        target = EDITIONS / (edition_name(speaker) + ".wav")
        steps.append((speaker, source, script, target))
    return steps


def copy_edition(source, script, target):
    sidecar = target.with_suffix(".txt")
    if target.exists() and digest(target) != digest(source):
        raise SystemExit(f"{target} already exists with different audio; refusing to overwrite")
    if not target.exists():
        shutil.copy2(source, target)
    if sidecar.exists() and sidecar.read_text(encoding="utf-8").strip() != script:
        raise SystemExit(f"{sidecar} already exists with a different script; refusing to overwrite")
    sidecar.write_text(script + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    steps = plan(json.loads(CAST.read_text(encoding="utf-8")))
    sm = StateManager(str(DB))
    voices = sm.get_voice_map()
    for speaker, source, script, target in steps:
        previous = voices.get(speaker)
        previous = previous["path"] if isinstance(previous, dict) else previous
        print(f"{speaker}: {previous or '(none)'} -> {target.relative_to(ROOT)}  [{source.relative_to(ROOT)}]")
        if args.dry_run:
            continue
        EDITIONS.mkdir(parents=True, exist_ok=True)
        copy_edition(source, script, target)
        sm.set_voice(speaker, str(target))
    print("Dry run only; nothing changed." if args.dry_run else f"Registered {len(steps)} designed voices.")


if __name__ == "__main__":
    main()
