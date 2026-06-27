"""Generate the studio-quality sound-design library via the ElevenLabs Sound
Effects API, driven by the curated tag catalogue in ``data/sfx/manifest.json``.

For every tag (13 ambience + 20 sfx + 7 music) it:
  1. Builds a Shadow-Slave-themed prompt from the tag's catalogue description.
  2. Calls POST /v1/text-to-sound-effects/convert (loop=True for ambience beds).
  3. Transcodes the returned MP3 to 16-bit PCM WAV @ 44.1 kHz into the right
     category dir (stereo for ambience/music, mono for one-shot sfx).
  4. Registers the clip in the live pipeline DB so the SoundDesigner resolves it.

The 40 written descriptions ARE the prompts — no studio-grade audio is
synthesised locally; ElevenLabs does the heavy lifting.

Usage (PowerShell):
    $env:ELEVENLABS_API_KEY = "sk_..."
    python scripts/generate_sfx_elevenlabs.py --limit 3        # cheap test batch
    python scripts/generate_sfx_elevenlabs.py                  # all missing
    python scripts/generate_sfx_elevenlabs.py --only cold_rain,sword_clash --force
    python scripts/generate_sfx_elevenlabs.py --dry-run        # print prompts, spend nothing

Flags:
    --limit N        stop after N generations (test the vibe before spending on 40)
    --only a,b,c     only these tags
    --category CAT   only one of: ambience | sfx | music
    --force          regenerate even if the WAV already exists
    --dry-run        print the prompt + plan for each tag, call no API
    --api-key KEY    override $ELEVENLABS_API_KEY
    --db PATH        DB to register into (default: src/data/pipeline.db, the app's)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

# Windows consoles default to cp1252; manifest descriptions use en-dashes. Force
# UTF-8 so a stray glyph can't raise UnicodeEncodeError mid-run (after spending
# credits). errors="replace" keeps logging best-effort even if reconfigure fails.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager  # noqa: E402

MANIFEST = ROOT / "data" / "sfx" / "manifest.json"
DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"
API_URL = "https://api.elevenlabs.io/v1/sound-generation"
# Best-first quality ladder. mp3_192 needs Creator tier, pcm_44100 needs Pro;
# we fall back automatically so a lower tier still succeeds at 128.
OUTPUT_FORMAT_LADDER = ["mp3_44100_192", "mp3_44100_128"]

# Mastering target: peak-normalise every clip to a consistent ceiling so the
# library is uniform and the mixer (which only attenuates) has full headroom.
# Transparent gain-staging — no compression, dynamics preserved.
TARGET_PEAK_DBFS = -1.0
MAX_NORM_GAIN_DB = 30.0   # don't amplify near-silence into noise

# Per-category generation policy. duration is clamped to ElevenLabs' [0.5, 30] s.
# A None duration lets the model pick the natural length (best for one-shots).
CATEGORY_POLICY = {
    "ambience": {"duration": 22.0, "loop": True,  "stereo": True,  "loopable": True,
                 "influence": 0.4,
                 "frame": ("{desc} Immersive dark-fantasy ambience bed, "
                           "cinematic, seamless and continuous, no music, "
                           "no speech, no sudden events.")},
    "music":    {"duration": 18.0, "loop": False, "stereo": True,  "loopable": False,
                 "influence": 0.35,
                 "frame": ("{desc} Cinematic dark-fantasy orchestral film score, "
                           "emotive, high production quality, no sound effects.")},
    "sfx":      {"duration": None, "loop": False, "stereo": False, "loopable": False,
                 "influence": 0.4,   # lower than before: gives the model room to
                                     # sound natural instead of thin/over-constrained
                 "frame": ("{desc} Dry, close, high-impact dark-fantasy game and "
                           "film sound effect, clean, no music, minimal reverb tail.")},
}

# Per-tag overrides for clips that need a richer, more specific prompt than the
# terse manifest description (one-shot SFX are the weak spot of text-to-SFX, so
# detail about attack/decay/timbre/perspective matters a lot). "prompt" is used
# VERBATIM (not wrapped in the category frame). Add tags here as you find duds,
# then re-roll just them: --only <tag> --force  (needs ElevenLabs credits).
TAG_OVERRIDES = {
    "sword_clash": {
        "prompt": ("Two heavy steel longswords colliding in a single powerful "
                   "clash. Bright metallic ring, fast hard attack, short "
                   "shimmering metallic decay. Forged iron, close-mic, dry, "
                   "cinematic dark-fantasy combat impact. No music, no reverb."),
        "duration": 1.5, "influence": 0.4,
    },
    "shadow_whoosh": {
        "prompt": ("A fast whoosh of living shadow sweeping past the listener. "
                   "Low airy swell that rises then fades into a soft sinister "
                   "tail. Ethereal, supernatural, smooth and dark. Dry, "
                   "cinematic dark fantasy. No music."),
        "duration": 2.0, "influence": 0.4,
    },
    "crowd_gasp": {
        "prompt": ("A small gathered crowd inside a stone hall reacting in "
                   "hushed alarm: a soft collective intake of breath, then a low "
                   "wave of uneasy murmuring whispers. Distant, restrained, dry."),
        "duration": 2.5, "influence": 0.4,
    },
}


def _load_catalogue() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = []
    for cat, block in data["categories"].items():
        for clip in block["clips"]:
            out.append({
                "tag": clip["tag"],
                "category": cat,
                "filename": clip["filename"],
                "description": clip.get("description", clip["tag"].replace("_", " ")),
                "dir": block["dir"],
            })
    return out


def _build_prompt(item: dict) -> str:
    override = TAG_OVERRIDES.get(item["tag"], {}).get("prompt")
    if override:
        return override.strip()
    pol = CATEGORY_POLICY[item["category"]]
    return pol["frame"].format(desc=item["description"]).strip()


def _policy_for(item: dict) -> dict:
    """Category policy with per-tag duration/influence overrides applied."""
    pol = dict(CATEGORY_POLICY[item["category"]])
    ov = TAG_OVERRIDES.get(item["tag"], {})
    if "duration" in ov:
        pol["duration"] = ov["duration"]
    if "influence" in ov:
        pol["influence"] = ov["influence"]
    return pol


def _generate(api_key: str, prompt: str, policy: dict, retries: int = 4) -> tuple[bytes, str]:
    """Return (audio_bytes, output_format). Walks the quality ladder, dropping to
    a lower format only when the tier rejects the requested one."""
    body = {"text": prompt, "loop": policy["loop"],
            "prompt_influence": policy["influence"]}
    if policy["duration"] is not None:
        body["duration_seconds"] = max(0.5, min(30.0, policy["duration"]))
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

    for fmt in OUTPUT_FORMAT_LADDER:
        for attempt in range(1, retries + 1):
            r = requests.post(API_URL, headers=headers,
                              params={"output_format": fmt}, json=body, timeout=180)
            if r.status_code == 200:
                return r.content, fmt
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = min(30, 2 ** attempt)
                print(f"    transient {r.status_code}; retry {attempt}/{retries-1} "
                      f"in {wait}s")
                time.sleep(wait)
                continue
            # Tier doesn't allow this format -> try the next (lower) one.
            if r.status_code in (400, 403, 422) and fmt != OUTPUT_FORMAT_LADDER[-1]:
                print(f"    {fmt} rejected ({r.status_code}); falling back")
                break
            raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:400]}")
    raise RuntimeError("exhausted output-format ladder")


def _peak_dbfs(wav: Path) -> float:
    """Measured sample-peak in dBFS via ffmpeg volumedetect (0.0 = full scale)."""
    r = subprocess.run(["ffmpeg", "-i", str(wav), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume:" in line:
            try:
                return float(line.split("max_volume:")[1].strip().split(" ")[0])
            except (ValueError, IndexError):
                break
    return 0.0


def _master(audio_bytes: bytes, src_fmt: str, dest: Path, stereo: bool) -> float:
    """Decode -> measure peak -> apply transparent normalising gain + 20 Hz
    DC-block high-pass -> write 16-bit PCM WAV @ 44.1 kHz. Returns applied gain dB.

    Two passes (measure, then apply) keep it a pure gain change: no compression,
    no limiting, dynamics fully preserved — studio gain-staging, not loudness war.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = ".mp3" if src_fmt.startswith("mp3") else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        raw_path = Path(tmp.name)
        raw_path.write_bytes(audio_bytes)
    decoded = raw_path.with_suffix(".dec.wav")
    try:
        # 1) Decode to WAV at the target rate/channels (no level change yet).
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_path), "-c:a", "pcm_s16le",
             "-ar", "44100", "-ac", "2" if stereo else "1", str(decoded)],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(f"decode failed:\n{r.stderr.decode()[-600:]}")

        # 2) Measure peak, compute the transparent gain to TARGET_PEAK_DBFS.
        gain = TARGET_PEAK_DBFS - _peak_dbfs(decoded)
        gain = max(-MAX_NORM_GAIN_DB, min(MAX_NORM_GAIN_DB, gain))

        # 3) Apply gain + DC-block, write the mastered clip.
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", str(decoded),
             "-af", f"volume={gain:.2f}dB,highpass=f=20",
             "-c:a", "pcm_s16le", "-ar", "44100",
             "-ac", "2" if stereo else "1", str(dest)],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(f"master failed:\n{r.stderr.decode()[-600:]}")
        return gain
    finally:
        for p in (raw_path, decoded):
            try:
                p.unlink()
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the SFX library via ElevenLabs")
    ap.add_argument("--limit", type=int, default=0, help="stop after N generations")
    ap.add_argument("--only", default="", help="comma-separated tags")
    ap.add_argument("--category", choices=["ambience", "sfx", "music"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()

    import os
    api_key = args.api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: no API key. Set $env:ELEVENLABS_API_KEY or pass --api-key.\n"
              "       Get one at https://elevenlabs.io/app/settings/api-keys")
        return 2

    only = {t.strip() for t in args.only.split(",") if t.strip()}
    catalogue = _load_catalogue()
    if args.category:
        catalogue = [c for c in catalogue if c["category"] == args.category]
    if only:
        catalogue = [c for c in catalogue if c["tag"] in only]

    sm = None if args.dry_run else StateManager(args.db)

    done = skipped = failed = 0
    for item in catalogue:
        if args.limit and done >= args.limit:
            print(f"\n[limit] stopped after {done} generations.")
            break

        dest = ROOT / item["dir"] / item["filename"]
        rel_path = f"{item['dir']}/{item['filename']}"
        policy = _policy_for(item)
        prompt = _build_prompt(item)

        if dest.exists() and not args.force:
            skipped += 1
            print(f"[skip] {item['tag']:<22} (exists)")
            continue

        if args.dry_run:
            dur = policy["duration"] or "auto"
            print(f"[dry] {item['category']:<8} {item['tag']:<22} "
                  f"dur={dur} loop={policy['loop']}\n      {prompt}")
            done += 1
            continue

        try:
            print(f"[gen] {item['category']:<8} {item['tag']:<22} ...", flush=True)
            audio, fmt = _generate(api_key, prompt, policy)
            gain = _master(audio, fmt, dest, stereo=policy["stereo"])
            sm.set_sfx_asset(
                tag=item["tag"], category=item["category"], audio_path=rel_path,
                display_name=item["tag"].replace("_", " ").title(),
                loopable=policy["loopable"],
            )
            done += 1
            print(f"      -> {rel_path} ({dest.stat().st_size//1024} KB, "
                  f"{fmt}, {gain:+.1f}dB norm) registered")
        except Exception as e:  # one bad tag must not abort the whole run
            failed += 1
            print(f"      FAILED {item['tag']}: {e}")

    print(f"\n=== {done} generated, {skipped} skipped, {failed} failed ===")
    if not args.dry_run and done:
        print("Re-render the demo to hear them in a mix:\n"
              "    python scripts/demo_sound_design.py   (uses synth clips; "
              "swap to library tags to A/B the real ones)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
