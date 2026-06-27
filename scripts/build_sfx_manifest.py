"""
Generate data/sfx/manifest.json — the sound-design clip catalogue.
================================================================
The manifest is a HUMAN-FACING catalogue of the curated cue vocabulary: every
tag Claude is allowed to emit, what sound to source for it, its default mix gain,
and where to drop the file. The library that actually renders is the DB
(`sfx_assets`, populated by uploading clips in the UI's Sound tab / POST /api/sfx);
this manifest just tells you what to source and register.

Source of truth is cue_io.CUE_VOCAB + SFX_TAG_ALIASES, so the manifest can never
drift from what the model emits. Re-run after editing the vocabulary:

    python scripts/build_sfx_manifest.py

Idempotent: regenerates manifest.json and ensures data/sfx/{ambience,sfx,music}/
exist (with .gitkeep). Does not touch any registered clips.
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from cue_io import CUE_VOCAB, SFX_TAG_ALIASES, _DEFAULT_GAIN_DB  # noqa: E402

_SFX_DIR = _ROOT / "data" / "sfx"

# One-line sourcing hint per tag — what the clip should actually contain. Keep
# these short; they guide a search on freesound.org / other CC0 libraries.
DESCRIPTIONS = {
    # ── ambience (loopable beds, ~10-30 s, seamless) ──────────────────────────
    "dream_realm_void":  "Featureless low hum / sub-bass drone — the Dream Realm's empty dark.",
    "nightmare_whispers": "Distant indistinct whispers, unsettling, no words.",
    "antarctic_wind":    "Steady cold wind, howling gusts, no debris.",
    "cold_rain":         "Even rainfall on stone/ground, no thunder.",
    "dungeon_drip":      "Damp stone room tone with sparse water drips, faint echo.",
    "ruined_halls":      "Hollow stone-corridor reverb, faint settling creaks.",
    "forest_night":      "Night forest: crickets, soft leaves, occasional owl.",
    "market_crowd":      "Busy outdoor crowd murmur, no distinct speech.",
    "tavern_murmur":     "Indoor crowd chatter, clinking mugs, warm room tone.",
    "open_sea":          "Open-water swell, gentle waves, distant gulls.",
    "storm_surge":       "Heavy storm: wind + rain + crashing surf.",
    "campfire_night":    "Crackling campfire with quiet night ambience.",
    "sanctuary_calm":    "Calm safe-haven tone, soft air, faint warm resonance.",
    # ── sfx (one-shots, <2 s, dry) ────────────────────────────────────────────
    "sword_clash":       "Two metal blades striking, sharp ring.",
    "sword_draw":        "Single sword unsheathing, metallic shing.",
    "shield_block":      "Impact on metal/wood shield, dull clang.",
    "arrow_whoosh":      "Single arrow/projectile flying past.",
    "bone_crack":        "Sharp bone snap / crunch.",
    "monster_roar":      "Large beast roar, deep and aggressive.",
    "monster_screech":   "High inhuman screech / shriek.",
    "flesh_tear":        "Wet tearing / rending impact.",
    "magic_cast":        "Generic spell-cast whoosh with energy shimmer.",
    "shadow_whoosh":     "Dark, airy whoosh — shadow movement / teleport.",
    "rune_activate":     "Crystalline rune/glyph powering up.",
    "spell_notification": "Short clean chime — the System/Spell prompt cue.",
    "heartbeat":         "Single slow heavy heartbeat thud (loopable optional).",
    "door_creak":        "Heavy wooden/stone door creaking open.",
    "chains_rattle":     "Metal chains shifting / rattling.",
    "footsteps_stone":   "A few footsteps on stone.",
    "thunder_crack":     "Sharp close thunderclap.",
    "fire_burst":        "Sudden flame ignition / fireball burst.",
    "water_splash":      "Single body/object splash into water.",
    "crowd_gasp":        "Crowd inhale / collective gasp.",
    # ── music (short scored swells, ~6-12 s) ──────────────────────────────────
    "dread_low_drone":   "Low ominous drone, building dread, no melody.",
    "sorrow_strings":    "Slow mournful strings, grief.",
    "tension_rise":      "Rising tension bed, pulse + crescendo.",
    "battle_pulse":      "Driving percussive combat motif.",
    "triumph_swell":     "Heroic major-key swell, victory.",
    "eerie_choir":       "Wordless unsettling choral pad.",
    "mystery_shimmer":   "Curious shimmering bells/pad, intrigue.",
}

# Roughly how long the sourced clip should be, per category.
LENGTH_HINT = {
    "ambience": "10-30 s, seamlessly loopable (engine loops short beds)",
    "sfx":      "<2 s one-shot, dry (no baked reverb/tail where avoidable)",
    "music":    "6-12 s scored swell; the engine trims+fades to the cue length",
}

EXT = ".wav"  # 16-bit PCM 44.1 kHz preferred (engine transcodes others on upload)


def build() -> dict:
    categories = {}
    for cat, tags in CUE_VOCAB.items():
        clips = [
            {
                "tag": tag,
                "filename": f"{tag}{EXT}",
                "default_gain_db": _DEFAULT_GAIN_DB.get(cat),
                "description": DESCRIPTIONS.get(tag, ""),
            }
            for tag in tags
        ]
        categories[cat] = {
            "dir": f"data/sfx/{cat}",
            "default_gain_db": _DEFAULT_GAIN_DB.get(cat),
            "length_hint": LENGTH_HINT.get(cat),
            "count": len(clips),
            "clips": clips,
        }

    missing = [t for cat in CUE_VOCAB.values() for t in cat if t not in DESCRIPTIONS]

    return {
        "_about": (
            "Catalogue of the curated sound-design vocabulary. Source one clip per "
            "tag (CC0 / royalty-free), drop it under the category 'dir', then "
            "register it in the UI Sound tab (or POST /api/sfx). Only registered, "
            "reviewed cues render, and only when sound design is enabled at "
            "generation time. Regenerate with scripts/build_sfx_manifest.py."
        ),
        "_sourcing": (
            "Recommended CC0 sources: freesound.org (filter License = Creative "
            "Commons 0), Pixabay, mixkit. Prefer clean, dry, mono-or-stereo clips; "
            "the engine adds fades, ducking and a final limiter. Confirm each "
            "clip's licence permits redistribution before committing audio."
        ),
        "preferred_format": "16-bit PCM WAV, 44.1 kHz (other formats transcoded on upload)",
        "total_tags": sum(len(t) for t in CUE_VOCAB.values()),
        "categories": categories,
        "aliases": SFX_TAG_ALIASES,
        "_missing_descriptions": missing,
    }


def main() -> None:
    for cat in CUE_VOCAB:
        d = _SFX_DIR / cat
        d.mkdir(parents=True, exist_ok=True)
        gk = d / ".gitkeep"
        if not gk.exists():
            gk.write_text("", encoding="utf-8")

    manifest = build()
    out = _SFX_DIR / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {out}")
    print(f"  {manifest['total_tags']} tags across {len(manifest['categories'])} categories")
    if manifest["_missing_descriptions"]:
        print(f"  WARNING: tags without descriptions: {manifest['_missing_descriptions']}")
    else:
        print("  all tags described")


if __name__ == "__main__":
    main()
