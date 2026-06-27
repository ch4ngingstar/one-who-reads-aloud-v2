"""Ingest locally-sourced sound clips (e.g. CC0 downloads from freesound.org /
Pixabay / mixkit) into the sound-design library — mastered + registered exactly
like the ElevenLabs generator, so AI-generated and hand-sourced clips are
indistinguishable downstream.

Mirrors the voices workflow: drop files in a folder, run the script.

Naming: each file's stem (minus extension) must be a catalogue tag from
data/sfx/manifest.json — e.g. `sword_clash.wav`, `shadow_whoosh.mp3`,
`crowd_gasp.flac`. Any ffmpeg-readable format works (wav/mp3/flac/ogg/m4a).
Filenames with a trailing `__something` are allowed for A/B variants and ignored
up to the `__` (so `sword_clash__freesound12345.wav` -> tag `sword_clash`).

Mastering (identical to the generator): decode -> peak-normalise to -1 dBFS
(transparent gain, no compression) -> 20 Hz DC-block high-pass -> 16-bit PCM WAV
44.1 kHz, stereo for ambience/music, mono for sfx. Registers in the live DB.

Usage (PowerShell):
    # 1) put CC0 downloads in data/sfx/_incoming/ named by tag
    # 2) run:
    python scripts/ingest_local_sfx.py
    python scripts/ingest_local_sfx.py --src "C:\\path\\to\\downloads"
    python scripts/ingest_local_sfx.py --dry-run     # show the tag mapping only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from state_manager import StateManager  # noqa: E402

MANIFEST = ROOT / "data" / "sfx" / "manifest.json"
DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"
DEFAULT_SRC = ROOT / "data" / "sfx" / "_incoming"
TARGET_PEAK_DBFS = -1.0
MAX_NORM_GAIN_DB = 30.0
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif"}


def _catalogue() -> dict:
    """tag -> {category, filename, dir, loopable} from the manifest."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for cat, block in data["categories"].items():
        loopable = cat == "ambience"
        for clip in block["clips"]:
            out[clip["tag"]] = {"category": cat, "filename": clip["filename"],
                                "dir": block["dir"], "loopable": loopable}
    return out


def _tag_from_name(path: Path) -> str:
    stem = path.stem
    return stem.split("__", 1)[0].strip()


def _peak_dbfs(wav: Path) -> float:
    r = subprocess.run(["ffmpeg", "-i", str(wav), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume:" in line:
            try:
                return float(line.split("max_volume:")[1].strip().split(" ")[0])
            except (ValueError, IndexError):
                break
    return 0.0


def _master(src: Path, dest: Path, stereo: bool) -> float:
    dest.parent.mkdir(parents=True, exist_ok=True)
    decoded = Path(tempfile.mktemp(suffix=".dec.wav"))
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-c:a", "pcm_s16le", "-ar", "44100",
             "-ac", "2" if stereo else "1", str(decoded)],
            capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"decode failed:\n{r.stderr.decode()[-500:]}")
        gain = TARGET_PEAK_DBFS - _peak_dbfs(decoded)
        gain = max(-MAX_NORM_GAIN_DB, min(MAX_NORM_GAIN_DB, gain))
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(decoded),
             "-af", f"volume={gain:.2f}dB,highpass=f=20",
             "-c:a", "pcm_s16le", "-ar", "44100",
             "-ac", "2" if stereo else "1", str(dest)],
            capture_output=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"master failed:\n{r.stderr.decode()[-500:]}")
        return gain
    finally:
        try:
            decoded.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest local CC0 sound clips")
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src_dir = Path(args.src)
    if not src_dir.exists():
        src_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created {src_dir}. Drop CC0 clips here named by tag "
              f"(e.g. sword_clash.wav), then re-run.")
        return 0

    cat = _catalogue()
    files = [p for p in sorted(src_dir.iterdir())
             if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    if not files:
        print(f"No audio files in {src_dir} (looked for {sorted(AUDIO_EXTS)}).")
        return 0

    sm = None if args.dry_run else StateManager(args.db)
    done = failed = 0
    for f in files:
        tag = _tag_from_name(f)
        meta = cat.get(tag)
        if not meta:
            print(f"[skip] {f.name}: stem '{tag}' is not a catalogue tag "
                  f"(see manifest.json). Rename to a known tag.")
            failed += 1
            continue

        dest = ROOT / meta["dir"] / meta["filename"]
        rel = f"{meta['dir']}/{meta['filename']}"
        stereo = meta["category"] in ("ambience", "music")
        if args.dry_run:
            print(f"[dry] {f.name:<32} -> {tag} ({meta['category']}) -> {rel}")
            done += 1
            continue
        try:
            gain = _master(f, dest, stereo=stereo)
            sm.set_sfx_asset(tag=tag, category=meta["category"], audio_path=rel,
                             display_name=tag.replace("_", " ").title(),
                             loopable=meta["loopable"])
            done += 1
            print(f"[ok]  {tag:<22} <- {f.name}  ({gain:+.1f}dB norm) -> {rel}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {tag}: {e}")

    print(f"\n=== {done} ingested, {failed} skipped/failed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
