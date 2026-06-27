"""Fetch real, recorded CC0 sound effects from Freesound.org for each catalogue
tag and stage them in data/sfx/_incoming/ ready for scripts/ingest_local_sfx.py.

Why this exists: AI text-to-SFX (ElevenLabs) is great at ambience/drones but weak
at discrete one-shot hits (sword clashes, monster roars, etc.). Freesound's CC0
pool has real recordings that beat it — but downloading needs a free API token.

Auth: a Freesound API token (NOT OAuth). Get one in ~60 s at
    https://freesound.org/apiv2/apply/
then either set $env:FREESOUND_API_KEY or pass --token. Token auth can search and
read the public preview URLs (high-quality MP3); we download `preview-hq-mp3`,
which for short one-shots is sonically indistinguishable from the original and is
the same CC0 sound. (The full-resolution /download/ endpoint needs OAuth2.)

Licence: we filter strictly to `license:"Creative Commons 0"` so every clip is
safe to redistribute in a public repo with no attribution required. A provenance
sidecar (sources JSON) is still written for transparency.

Usage (PowerShell):
    $env:FREESOUND_API_KEY = "..."
    python scripts/fetch_sfx_freesound.py                 # all one-shot sfx
    python scripts/fetch_sfx_freesound.py --category sfx  # default
    python scripts/fetch_sfx_freesound.py --only sword_clash,monster_roar
    python scripts/fetch_sfx_freesound.py --all-categories  # also ambience+music
    python scripts/fetch_sfx_freesound.py --dry-run         # print queries only
Then:
    python scripts/ingest_local_sfx.py     # masters + registers what was fetched
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MANIFEST = ROOT / "data" / "sfx" / "manifest.json"
INCOMING = ROOT / "data" / "sfx" / "_incoming"
SOURCES = INCOMING / "SOURCES.json"
SEARCH_URL = "https://freesound.org/apiv2/search/text/"

# Per-tag search query + max duration (s). Queries are tuned for the catalogue's
# dark-fantasy intent; CC0 filtering is applied on top. Duration caps keep one-shots
# tight and ambience/music long. Override freely as you audition results.
QUERIES = {
    # --- one-shot sfx (cinematic/"designed" intent; retro/8-bit/rpg auto-skipped) ---
    "sword_clash": ("metal swords clashing impact", 0.2, 3.0),
    "sword_draw": ("sword unsheathe metal ring", 0.2, 3.0),
    "shield_block": ("shield hit", 0.1, 4.0),
    "arrow_whoosh": ("arrow flyby whoosh", 0.1, 2.0),
    "bone_crack": ("bone crack break", 0.1, 2.0),
    "monster_roar": ("monster roar creature", 0.5, 4.0),
    "monster_screech": ("monster screech", 0.4, 4.0),
    "flesh_tear": ("gore stab squelch flesh", 0.1, 3.0),
    "magic_cast": ("magic spell", 0.3, 3.0),
    "shadow_whoosh": ("cinematic whoosh dark", 0.2, 3.0),
    "rune_activate": ("shimmer", 0.2, 3.0),
    "spell_notification": ("magic chime bell fantasy", 0.2, 2.5),
    "heartbeat": ("heartbeat", 0.3, 3.0),
    "door_creak": ("heavy wooden door creak", 0.5, 4.0),
    "chains_rattle": ("chains rattle", 0.3, 4.0),
    "footsteps_stone": ("footsteps stone", 0.5, 4.0),
    "thunder_crack": ("thunder strike", 0.5, 8.0),
    "fire_burst": ("fireball", 0.2, 4.0),
    "water_splash": ("water splash big", 0.2, 3.0),
    "crowd_gasp": ("crowd gasp", 0.4, 4.0),
    # --- ambience beds (optional; --all-categories) ---
    "dream_realm_void": ("dark drone ambience void", 8.0, 60.0),
    "nightmare_whispers": ("creepy whispers ambience", 8.0, 60.0),
    "antarctic_wind": ("cold wind howling loop", 8.0, 60.0),
    "cold_rain": ("rain ambience steady", 8.0, 60.0),
    "dungeon_drip": ("cave water drip ambience", 8.0, 60.0),
    "ruined_halls": ("dungeon ambience stone hall", 8.0, 60.0),
    "forest_night": ("forest night crickets ambience", 8.0, 60.0),
    "market_crowd": ("crowd murmur ambience market", 8.0, 60.0),
    "tavern_murmur": ("tavern ambience crowd", 8.0, 60.0),
    "open_sea": ("ocean waves ambience", 8.0, 60.0),
    "storm_surge": ("storm rain wind ambience", 8.0, 60.0),
    "campfire_night": ("campfire crackle ambience", 8.0, 60.0),
    "sanctuary_calm": ("calm ambient drone peaceful", 8.0, 60.0),
    # --- music swells (optional; --all-categories) ---
    "dread_low_drone": ("dark horror drone cinematic", 6.0, 40.0),
    "sorrow_strings": ("sad strings emotional", 6.0, 40.0),
    "tension_rise": ("tension riser suspense", 6.0, 40.0),
    "battle_pulse": ("epic battle drums percussion", 6.0, 40.0),
    "triumph_swell": ("triumphant orchestral victory", 6.0, 40.0),
    "eerie_choir": ("eerie choir horror", 6.0, 40.0),
    "mystery_shimmer": ("mysterious shimmer magical", 6.0, 40.0),
}


def _catalogue() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {}
    for cat, block in data["categories"].items():
        for clip in block["clips"]:
            out[clip["tag"]] = cat
    return out


# Substrings in a clip name that flag amateur / retro / non-cinematic results we'd
# rather skip when a better candidate exists (8-bit RPG synth blips, chiptune, raw
# synth tones, anything that's actually music/speech). Falls back to top result if
# every candidate is filtered out.
_AVOID = ("8-bit", "8bit", "chiptune", "retro", "rpg", "nes", "snes", "sine",
          "square wave", "beep", "synth", "song", "music", "melody", "vocal",
          "speech", "tts", "menu", "button", "trailer", "cartoon", "wink")


def _pick(results: list[dict]) -> dict | None:
    if not results:
        return None
    for r in results:
        name = (r.get("name") or "").lower()
        tags = " ".join(r.get("tags", [])).lower()
        if any(k in name or k in tags for k in _AVOID):
            continue
        return r
    return results[0]  # everything filtered -> least-bad (most downloaded)


def _get_sound(token: str, sound_id: int) -> dict:
    """Fetch one specific sound by id (for hand-picked overrides via --pick)."""
    r = requests.get(
        f"https://freesound.org/apiv2/sounds/{sound_id}/",
        params={"fields": "id,name,license,duration,username,previews,num_downloads,url"},
        headers={"Authorization": f"Token {token}"}, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"sound #{sound_id} fetch {r.status_code}: {r.text[:200]}")
    s = r.json()
    # The detail endpoint returns the license as a URL (publicdomain/zero/1.0),
    # while search returns the text "Creative Commons 0" — accept either form.
    lic = (s.get("license") or "").lower()
    if "creative commons 0" not in lic and "publicdomain/zero" not in lic:
        raise RuntimeError(f"sound #{sound_id} is not CC0 ({s.get('license')})")
    return s


def _search(token: str, query: str, min_d: float, max_d: float) -> list[dict]:
    params = {
        "query": query,
        "filter": f'license:"Creative Commons 0" duration:[{min_d} TO {max_d}]',
        "fields": "id,name,license,duration,username,previews,num_downloads,url,tags",
        "sort": "downloads_desc",
        "page_size": 15,
    }
    r = requests.get(SEARCH_URL, params=params,
                     headers={"Authorization": f"Token {token}"}, timeout=45)
    if r.status_code == 401:
        raise RuntimeError("401 Unauthorized — bad/expired token. Re-check "
                           "$FREESOUND_API_KEY (apply at "
                           "https://freesound.org/apiv2/apply/).")
    if r.status_code != 200:
        raise RuntimeError(f"Freesound {r.status_code}: {r.text[:300]}")
    return r.json().get("results", [])


def _download_preview(token: str, result: dict, dest: Path) -> None:
    url = (result.get("previews") or {}).get("preview-hq-mp3")
    if not url:
        raise RuntimeError("no preview-hq-mp3 in result")
    # Preview CDN is public; send token too in case of throttling.
    r = requests.get(url, headers={"Authorization": f"Token {token}"},
                     timeout=90, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"preview download {r.status_code}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        for chunk in r.iter_content(8192):
            fh.write(chunk)
    if dest.stat().st_size < 1024:
        raise RuntimeError("downloaded file suspiciously small")


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch CC0 SFX from Freesound")
    ap.add_argument("--token", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--pick", default="", help="hand-pick by id: tag=freesound_id,tag=id")
    ap.add_argument("--category", choices=["ambience", "sfx", "music"], default="sfx")
    ap.add_argument("--all-categories", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = args.token or os.environ.get("FREESOUND_API_KEY", "")
    if not token and not args.dry_run:
        print("ERROR: no token. Set $env:FREESOUND_API_KEY or pass --token.\n"
              "       Get a free one at https://freesound.org/apiv2/apply/")
        return 2

    cat = _catalogue()
    picks = {}
    for kv in args.pick.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            picks[k.strip()] = int(v.strip())
    only = {t.strip() for t in args.only.split(",") if t.strip()} | set(picks)
    tags = [t for t in cat if t in QUERIES]
    if only:
        tags = [t for t in tags if t in only]
    elif not args.all_categories:
        tags = [t for t in tags if cat[t] == args.category]

    sources = {}
    if SOURCES.exists():
        try:
            sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        except Exception:
            sources = {}

    done = failed = 0
    for tag in tags:
        query, min_d, max_d = QUERIES[tag]
        if args.dry_run:
            print(f"[dry] {cat[tag]:<8} {tag:<20} q='{query}' dur[{min_d},{max_d}]")
            done += 1
            continue
        try:
            if tag in picks:
                pick = _get_sound(token, picks[tag])
            else:
                results = _search(token, query, min_d, max_d)
                pick = _pick(results)
            if not pick:
                print(f"[none] {tag:<20} no CC0 match for '{query}' — retune query")
                failed += 1
                continue
            dest = INCOMING / f"{tag}.mp3"
            _download_preview(token, pick, dest)
            sources[tag] = {"freesound_id": pick["id"], "name": pick["name"],
                            "username": pick["username"], "license": pick["license"],
                            "url": pick.get("url", ""),
                            "duration": round(pick.get("duration", 0), 2)}
            done += 1
            print(f"[ok]  {tag:<20} <- #{pick['id']} \"{pick['name'][:40]}\" "
                  f"by {pick['username']} ({pick.get('duration',0):.1f}s, "
                  f"{pick.get('num_downloads',0)} dls)")
            time.sleep(0.5)  # be polite to the API
        except Exception as e:
            failed += 1
            print(f"[FAIL] {tag}: {e}")

    if not args.dry_run and sources:
        SOURCES.parent.mkdir(parents=True, exist_ok=True)
        SOURCES.write_text(json.dumps(sources, indent=2), encoding="utf-8")

    print(f"\n=== {done} fetched, {failed} failed ===")
    if not args.dry_run and done:
        print("Provenance: data/sfx/_incoming/SOURCES.json")
        print("Next:  python scripts/ingest_local_sfx.py   (masters + registers)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
