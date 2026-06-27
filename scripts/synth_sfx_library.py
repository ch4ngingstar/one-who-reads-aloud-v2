"""Procedurally synthesise the FULL sound-design library (all 40 catalogue tags)
with ffmpeg DSP — no external downloads, no API key, and (importantly) NO licence
encumbrance: synthesised audio is original and safe to commit to a public repo.

This is the zero-dependency baseline path alongside the two sourcing scripts:
  * scripts/generate_sfx_elevenlabs.py  -> studio-quality, needs an API key + credits
  * scripts/ingest_local_sfx.py         -> hand-sourced CC0 clips, needs a human ear

Every tag is built from oscillators + filtered noise (sine / anoisesrc + highpass,
lowpass, bandpass, tremolo, vibrato, aecho, acrusher, adelay, amix), then mastered
IDENTICALLY to the other two scripts: decode -> peak-normalise to -1 dBFS
(transparent gain, no compression) -> 20 Hz DC-block high-pass -> 16-bit PCM WAV
44.1 kHz, stereo for ambience/music, mono for one-shot sfx. Registers in the live DB
so the SoundDesigner resolves it exactly like a real clip.

These are deliberately characterful *placeholders*: drop a better CC0 / ElevenLabs
clip in for any tag later (same filename) and re-run ingest to upgrade in place.

Usage (PowerShell):
    python scripts/synth_sfx_library.py                # build all missing
    python scripts/synth_sfx_library.py --force        # rebuild everything
    python scripts/synth_sfx_library.py --only cold_rain,sword_clash --force
    python scripts/synth_sfx_library.py --category sfx
    python scripts/synth_sfx_library.py --dry-run      # list the plan, write nothing
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
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from state_manager import StateManager  # noqa: E402

MANIFEST = ROOT / "data" / "sfx" / "manifest.json"
DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"
SR = 44100
TARGET_PEAK_DBFS = -1.0
MAX_NORM_GAIN_DB = 30.0

# Each recipe: a list of lavfi source strings (one ffmpeg -f lavfi input each) and
# a filter_complex graph that consumes [0:a],[1:a],... and produces [out]. Duration
# is applied via -t on every input so infinite sources (sine/anoisesrc) terminate.
# Keep pre-master peaks <= ~1.0: amix defaults to normalize=1 (averages inputs), and
# single-source sine peaks at 1.0 — the two-pass mastering then sets the real level.
Recipe = dict  # {"srcs": [str], "graph": str, "dur": float}


def _amb(graph: str, dur: float = 20.0, srcs=None) -> Recipe:
    return {"srcs": srcs or ["anoisesrc=c=pink:a=0.6:r=%d" % SR], "graph": graph, "dur": dur}


# --- 13 ambience beds (stereo, ~20 s, steady/loopable: no in/out fades) ----------
AMBIENCE = {
    # Featureless sub-bass void: deep brown rumble under a 40 Hz sub sine.
    "dream_realm_void": {
        "srcs": ["anoisesrc=c=brown:a=0.7:r=%d" % SR, "sine=f=40:r=%d" % SR],
        "graph": "[0:a]lowpass=f=180,volume=0.9[a];[1:a]volume=0.6[b];"
                 "[a][b]amix=inputs=2[out]", "dur": 20.0},
    # Distant unsettling whispers: mid-band noise, slow tremolo, hall echo.
    "nightmare_whispers": _amb(
        "[0:a]highpass=f=700,lowpass=f=4500,tremolo=f=0.8:d=0.6,"
        "aecho=0.8:0.7:120|370:0.5|0.3[out]"),
    # Steady cold wind with gusts: band-limited noise, slow deep tremolo.
    "antarctic_wind": _amb(
        "[0:a]highpass=f=250,lowpass=f=2200,tremolo=f=0.18:d=0.8[out]",
        srcs=["anoisesrc=c=white:a=0.6:r=%d" % SR]),
    # Even rainfall: bright white noise rolled off, faint shimmer.
    "cold_rain": _amb(
        "[0:a]highpass=f=900,lowpass=f=9000,tremolo=f=0.5:d=0.2[out]",
        srcs=["anoisesrc=c=white:a=0.55:r=%d" % SR]),
    # Damp stone room: low room tone + sparse echoing drips.
    "dungeon_drip": {
        "srcs": ["anoisesrc=c=brown:a=0.4:r=%d" % SR, "sine=f=1600:r=%d" % SR],
        "graph": "[0:a]lowpass=f=500[a];"
                 "[1:a]tremolo=f=0.4:d=1,volume=0.3,"
                 "aecho=0.9:0.8:230|510:0.5|0.3[b];[a][b]amix=inputs=2[out]",
        "dur": 20.0},
    # Hollow stone corridor: lowpassed noise drenched in long reverb.
    "ruined_halls": _amb(
        "[0:a]lowpass=f=1600,aecho=0.8:0.85:330|620|900:0.5|0.35|0.2[out]"),
    # Night forest: high cricket hiss + airy bed.
    "forest_night": _amb(
        "[0:a]highpass=f=2600,lowpass=f=9000,tremolo=f=11:d=0.7[out]"),
    # Outdoor crowd murmur: low band noise, medium tremolo wash.
    "market_crowd": _amb(
        "[0:a]highpass=f=200,lowpass=f=1100,tremolo=f=5:d=0.6[out]",
        srcs=["anoisesrc=c=brown:a=0.6:r=%d" % SR]),
    # Indoor tavern: warmer, lower murmur with faint room echo.
    "tavern_murmur": _amb(
        "[0:a]highpass=f=150,lowpass=f=850,tremolo=f=4:d=0.5,"
        "aecho=0.7:0.6:90:0.25[out]", srcs=["anoisesrc=c=brown:a=0.6:r=%d" % SR]),
    # Open water swell: low noise with slow wave tremolo.
    "open_sea": _amb(
        "[0:a]lowpass=f=1500,tremolo=f=0.14:d=0.8[out]",
        srcs=["anoisesrc=c=white:a=0.5:r=%d" % SR]),
    # Heavy storm: full-band loud noise + faster gusting.
    "storm_surge": _amb(
        "[0:a]highpass=f=180,lowpass=f=6500,tremolo=f=0.5:d=0.7[out]",
        srcs=["anoisesrc=c=white:a=0.7:r=%d" % SR]),
    # Campfire: crackle hiss with irregular fast tremolo.
    "campfire_night": _amb(
        "[0:a]highpass=f=1800,lowpass=f=8000,tremolo=f=14:d=0.9[out]"),
    # Calm sanctuary: soft fifth pad (220+330 Hz), warm and still.
    "sanctuary_calm": {
        "srcs": ["sine=f=220:r=%d" % SR, "sine=f=330:r=%d" % SR],
        "graph": "[0:a]vibrato=f=0.3:d=0.2[a];[1:a]vibrato=f=0.25:d=0.2[b];"
                 "[a][b]amix=inputs=2,lowpass=f=2000,volume=0.7[out]", "dur": 20.0},
}

# --- 7 music swells (stereo, ~12 s, afade in for a scored entrance) ---------------
MUSIC = {
    # Low ominous drone: two close low sines beating + tremolo.
    "dread_low_drone": {
        "srcs": ["sine=f=55:r=%d" % SR, "sine=f=58:r=%d" % SR],
        "graph": "[0:a][1:a]amix=inputs=2,tremolo=f=0.3:d=0.5,lowpass=f=400,"
                 "afade=t=in:st=0:d=2[out]", "dur": 12.0},
    # Mournful strings: A-minor triad with vibrato, slow swell.
    "sorrow_strings": {
        "srcs": ["sine=f=220:r=%d" % SR, "sine=f=261.63:r=%d" % SR,
                 "sine=f=329.63:r=%d" % SR],
        "graph": "[0:a][1:a][2:a]amix=inputs=3,vibrato=f=5:d=0.4,lowpass=f=2500,"
                 "afade=t=in:st=0:d=3[out]", "dur": 12.0},
    # Rising tension: dissonant cluster crescendo via long fade-in + speeding pulse.
    "tension_rise": {
        "srcs": ["sine=f=110:r=%d" % SR, "sine=f=116.5:r=%d" % SR],
        "graph": "[0:a][1:a]amix=inputs=2,tremolo=f=3:d=0.7,afade=t=in:st=0:d=10[out]",
        "dur": 12.0},
    # Driving combat pulse: low sine gated into a fast percussive throb.
    "battle_pulse": {
        "srcs": ["sine=f=60:r=%d" % SR, "anoisesrc=c=brown:a=0.4:r=%d" % SR],
        "graph": "[0:a]tremolo=f=4:d=1[a];[1:a]lowpass=f=300,tremolo=f=4:d=0.9[b];"
                 "[a][b]amix=inputs=2,afade=t=in:st=0:d=1[out]", "dur": 12.0},
    # Heroic victory: C-major triad, bright, with a confident swell.
    "triumph_swell": {
        "srcs": ["sine=f=261.63:r=%d" % SR, "sine=f=329.63:r=%d" % SR,
                 "sine=f=392:r=%d" % SR],
        "graph": "[0:a][1:a][2:a]amix=inputs=3,vibrato=f=4:d=0.3,"
                 "afade=t=in:st=0:d=2.5[out]", "dur": 12.0},
    # Eerie wordless choir: voiced cluster, heavy vibrato + reverb.
    "eerie_choir": {
        "srcs": ["sine=f=196:r=%d" % SR, "sine=f=233:r=%d" % SR,
                 "sine=f=294:r=%d" % SR],
        "graph": "[0:a][1:a][2:a]amix=inputs=3,vibrato=f=6:d=0.6,bandpass=f=900:width_type=h:w=1600,"
                 "aecho=0.8:0.8:200|450:0.5|0.3,afade=t=in:st=0:d=2[out]", "dur": 12.0},
    # Mysterious shimmer: high bells with fast tremolo + echo tails.
    "mystery_shimmer": {
        "srcs": ["sine=f=880:r=%d" % SR, "sine=f=1318.5:r=%d" % SR],
        "graph": "[0:a][1:a]amix=inputs=2,tremolo=f=7:d=0.8,"
                 "aecho=0.8:0.7:150|330|520:0.5|0.35|0.2,afade=t=in:st=0:d=1.5[out]",
        "dur": 12.0},
}

# --- 20 one-shot sfx (mono, short, hard attack + quick decay) ---------------------
SFX = {
    # Two steel blades: inharmonic metallic partials, fast shimmering decay.
    "sword_clash": {
        "srcs": ["sine=f=1840:r=%d" % SR, "sine=f=2470:r=%d" % SR,
                 "sine=f=3100:r=%d" % SR],
        "graph": "[0:a][1:a][2:a]amix=inputs=3,highpass=f=1200,"
                 "afade=t=out:st=0.05:d=0.45[out]", "dur": 0.6},
    # Sword unsheathe: bright noise shing with a quick swell-then-cut.
    "sword_draw": {
        "srcs": ["anoisesrc=c=white:a=0.8:r=%d" % SR],
        "graph": "[0:a]highpass=f=3500,lowpass=f=11000,afade=t=in:st=0:d=0.08,"
                 "afade=t=out:st=0.18:d=0.3[out]", "dur": 0.55},
    # Shield block: low wooden/metal thud with a short metallic ring.
    "shield_block": {
        "srcs": ["sine=f=190:r=%d" % SR, "anoisesrc=c=brown:a=0.7:r=%d" % SR],
        "graph": "[0:a]volume=0.9[a];[1:a]lowpass=f=1400[b];"
                 "[a][b]amix=inputs=2,afade=t=out:st=0:d=0.3[out]", "dur": 0.4},
    # Arrow flyby: band-limited whoosh that rushes past.
    "arrow_whoosh": {
        "srcs": ["anoisesrc=c=white:a=0.7:r=%d" % SR],
        "graph": "[0:a]bandpass=f=2500:width_type=h:w=1800,afade=t=in:st=0:d=0.12,"
                 "afade=t=out:st=0.16:d=0.2[out]", "dur": 0.45},
    # Bone snap: very short hard cracking transient.
    "bone_crack": {
        "srcs": ["anoisesrc=c=white:a=0.9:r=%d" % SR],
        "graph": "[0:a]highpass=f=1500,lowpass=f=7000,afade=t=out:st=0:d=0.12,"
                 "acrusher=bits=8:mode=log:mix=0.4[out]", "dur": 0.2},
    # Large beast roar: low growling noise + sub sine, vibrato, swelling envelope.
    "monster_roar": {
        "srcs": ["anoisesrc=c=brown:a=0.8:r=%d" % SR, "sine=f=85:r=%d" % SR],
        "graph": "[0:a]lowpass=f=900,vibrato=f=18:d=0.6[a];[1:a]vibrato=f=12:d=0.5[b];"
                 "[a][b]amix=inputs=2,afade=t=in:st=0:d=0.2,"
                 "afade=t=out:st=1.1:d=0.5[out]", "dur": 1.6},
    # Inhuman screech: high shrieking sine with heavy vibrato + grit.
    "monster_screech": {
        "srcs": ["sine=f=1500:r=%d" % SR],
        "graph": "[0:a]vibrato=f=22:d=0.9,acrusher=bits=6:mode=log:mix=0.5,"
                 "highpass=f=900,afade=t=out:st=0.7:d=0.3[out]", "dur": 1.0},
    # Wet rending: short lowpassed noise burst with crunch.
    "flesh_tear": {
        "srcs": ["anoisesrc=c=pink:a=0.8:r=%d" % SR],
        "graph": "[0:a]lowpass=f=3000,acrusher=bits=7:mode=log:mix=0.5,"
                 "afade=t=out:st=0.15:d=0.4[out]", "dur": 0.6},
    # Spell cast: airy shimmer whoosh of high noise + bell tone.
    "magic_cast": {
        "srcs": ["anoisesrc=c=white:a=0.5:r=%d" % SR, "sine=f=1320:r=%d" % SR],
        "graph": "[0:a]highpass=f=2000,afade=t=in:st=0:d=0.3[a];"
                 "[1:a]tremolo=f=9:d=0.7,aecho=0.8:0.7:120:0.4[b];"
                 "[a][b]amix=inputs=2,afade=t=out:st=0.8:d=0.5[out]", "dur": 1.3},
    # Shadow movement: dark low airy whoosh, smooth swell + sinister tail.
    "shadow_whoosh": {
        "srcs": ["anoisesrc=c=brown:a=0.8:r=%d" % SR],
        "graph": "[0:a]lowpass=f=700,tremolo=f=2:d=0.5,afade=t=in:st=0:d=0.6,"
                 "afade=t=out:st=1.2:d=0.7[out]", "dur": 2.0},
    # Rune powering up: crystalline rising bells with echo.
    "rune_activate": {
        "srcs": ["sine=f=700:r=%d" % SR, "sine=f=1050:r=%d" % SR],
        "graph": "[0:a][1:a]amix=inputs=2,tremolo=f=12:d=0.8,"
                 "aecho=0.8:0.7:90|180:0.5|0.3,afade=t=in:st=0:d=0.4,"
                 "afade=t=out:st=0.8:d=0.3[out]", "dur": 1.1},
    # System/Spell prompt: clean two-note chime (G6 -> E7-ish).
    "spell_notification": {
        "srcs": ["sine=f=988:r=%d" % SR, "sine=f=1318.5:r=%d" % SR],
        "graph": "[0:a]afade=t=out:st=0:d=0.5[a];"
                 "[1:a]adelay=170|170,afade=t=out:st=0.17:d=0.5[b];"
                 "[a][b]amix=inputs=2[out]", "dur": 0.9},
    # Slow heavy heartbeat: lub-dub via a low thump echoed once.
    "heartbeat": {
        "srcs": ["sine=f=55:r=%d" % SR],
        "graph": "[0:a]afade=t=out:st=0:d=0.16,lowpass=f=200,"
                 "aecho=0.9:0.85:260:0.7[out]", "dur": 1.1},
    # Heavy door: low groaning creak via vibrato + bitcrush growl.
    "door_creak": {
        "srcs": ["sine=f=95:r=%d" % SR],
        "graph": "[0:a]vibrato=f=6:d=0.9,acrusher=bits=6:mode=log:mix=0.4,"
                 "lowpass=f=1200,afade=t=out:st=1.0:d=0.4[out]", "dur": 1.4},
    # Chains: high metallic rattle, fast tremolo + grit.
    "chains_rattle": {
        "srcs": ["anoisesrc=c=white:a=0.7:r=%d" % SR],
        "graph": "[0:a]highpass=f=3000,tremolo=f=18:d=0.9,acrusher=bits=7:mode=log:mix=0.4,"
                 "afade=t=out:st=0.7:d=0.3[out]", "dur": 1.0},
    # A few footsteps on stone: short low thuds echoed at intervals.
    "footsteps_stone": {
        "srcs": ["anoisesrc=c=brown:a=0.8:r=%d" % SR],
        "graph": "[0:a]lowpass=f=500,afade=t=out:st=0:d=0.12,"
                 "aecho=0.85:0.7:330|680|1020:0.6|0.5|0.4[out]", "dur": 1.4},
    # Close thunderclap: sharp full-band crack into a long lowpassed rumble.
    "thunder_crack": {
        "srcs": ["anoisesrc=c=brown:a=0.9:r=%d" % SR],
        "graph": "[0:a]lowpass=f=3500,afade=t=in:st=0:d=0.02,"
                 "afade=t=out:st=0.4:d=1.5[out]", "dur": 2.0},
    # Fireball ignition: noise whoomp swell with a bright burst on top.
    "fire_burst": {
        "srcs": ["anoisesrc=c=pink:a=0.8:r=%d" % SR],
        "graph": "[0:a]highpass=f=300,lowpass=f=6000,afade=t=in:st=0:d=0.08,"
                 "afade=t=out:st=0.4:d=0.5[out]", "dur": 1.0},
    # Splash: short band-limited water burst with a quick tail.
    "water_splash": {
        "srcs": ["anoisesrc=c=white:a=0.8:r=%d" % SR],
        "graph": "[0:a]bandpass=f=1800:width_type=h:w=2400,afade=t=out:st=0.1:d=0.5[out]",
        "dur": 0.7},
    # Crowd gasp: a soft collective inhale swell, voiced band, then settle.
    "crowd_gasp": {
        "srcs": ["anoisesrc=c=pink:a=0.7:r=%d" % SR],
        "graph": "[0:a]bandpass=f=700:width_type=h:w=900,afade=t=in:st=0:d=0.5,"
                 "afade=t=out:st=0.7:d=0.5[out]", "dur": 1.2},
}

RECIPES = {**AMBIENCE, **MUSIC, **SFX}


def _catalogue() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for cat, block in data["categories"].items():
        for clip in block["clips"]:
            out[clip["tag"]] = {"category": cat, "filename": clip["filename"],
                                "dir": block["dir"], "loopable": cat == "ambience"}
    return out


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


def _synth_raw(recipe: Recipe, dest_raw: Path, stereo: bool) -> None:
    """Render the recipe graph to a temp WAV (pre-master, mono internally)."""
    cmd = ["ffmpeg", "-y"]
    for src in recipe["srcs"]:
        cmd += ["-f", "lavfi", "-t", f"{recipe['dur']}", "-i", src]
    cmd += ["-filter_complex", recipe["graph"], "-map", "[out]",
            "-t", f"{recipe['dur']}", "-ar", str(SR), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest_raw)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"synth failed:\n{r.stderr.decode()[-600:]}")


def _master(raw: Path, dest: Path, stereo: bool) -> float:
    """Peak-normalise to -1 dBFS + 20 Hz DC-block; write final 16-bit WAV."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    gain = TARGET_PEAK_DBFS - _peak_dbfs(raw)
    gain = max(-MAX_NORM_GAIN_DB, min(MAX_NORM_GAIN_DB, gain))
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(raw),
         "-af", f"volume={gain:.2f}dB,highpass=f=20",
         "-c:a", "pcm_s16le", "-ar", str(SR),
         "-ac", "2" if stereo else "1", str(dest)],
        capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"master failed:\n{r.stderr.decode()[-600:]}")
    return gain


def main() -> int:
    ap = argparse.ArgumentParser(description="Procedurally synthesise the SFX library")
    ap.add_argument("--only", default="", help="comma-separated tags")
    ap.add_argument("--category", choices=["ambience", "sfx", "music"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()

    cat = _catalogue()
    missing = sorted(set(cat) - set(RECIPES))
    if missing:
        print(f"WARNING: no recipe for {len(missing)} catalogue tag(s): {missing}")

    only = {t.strip() for t in args.only.split(",") if t.strip()}
    tags = [t for t in cat if t in RECIPES]
    if args.category:
        tags = [t for t in tags if cat[t]["category"] == args.category]
    if only:
        tags = [t for t in tags if t in only]

    sm = None if args.dry_run else StateManager(args.db)
    done = skipped = failed = 0
    for tag in tags:
        meta = cat[tag]
        dest = ROOT / meta["dir"] / meta["filename"]
        rel = f"{meta['dir']}/{meta['filename']}"
        stereo = meta["category"] in ("ambience", "music")

        if dest.exists() and not args.force:
            skipped += 1
            print(f"[skip] {tag:<22} (exists)")
            continue
        if args.dry_run:
            print(f"[dry] {meta['category']:<8} {tag:<22} dur={RECIPES[tag]['dur']}s -> {rel}")
            done += 1
            continue

        raw = Path(tempfile.mktemp(suffix=".raw.wav"))
        try:
            _synth_raw(RECIPES[tag], raw, stereo)
            gain = _master(raw, dest, stereo=stereo)
            sm.set_sfx_asset(tag=tag, category=meta["category"], audio_path=rel,
                             display_name=tag.replace("_", " ").title(),
                             loopable=meta["loopable"])
            done += 1
            print(f"[ok]  {meta['category']:<8} {tag:<22} ({gain:+.1f}dB norm) -> {rel}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {tag}: {e}")
        finally:
            try:
                raw.unlink()
            except OSError:
                pass

    print(f"\n=== {done} synthesised, {skipped} skipped, {failed} failed ===")
    if not args.dry_run and done:
        print("Hear them in a mix:  python scripts/demo_sound_design.py")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
