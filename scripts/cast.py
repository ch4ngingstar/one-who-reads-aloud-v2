"""The casting loop: find who needs a voice, screen designed candidates, apply the owner's picks.

    python scripts/cast.py discover --projects 7 8 --min-chapter 2300
    python scripts/cast.py screen Jet "Saint Naeve" Azarax          # after design_voices.py
    python scripts/cast.py apply voice-casting-<pack>.json data/voice-design/round3/round3-key.json

The full loop is:  discover -> brief (profiles/voice-briefs.json) -> design (design_voices.py)
-> screen (this) -> audition (cast_round.py, blind engine takes) -> owner picks -> apply (this).
`apply` copies a picked designed clip to src/data/voices/editions/ with its exact script, points
the character at it (previous clips stay on disk), routes the character to the engine whose take
was picked, and logs the decision in profiles/cast-decisions.json. Protected voices are refused.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DB = ROOT / "src/data/pipeline.db"
DESIGN = ROOT / "data/voice-design"
EDITIONS = ROOT / "src/data/voices/editions"
PROFILE = ROOT / "profiles/full-cast.json"
DECISIONS = ROOT / "profiles/cast-decisions.json"
PROTECTED = {"narrator", "sunny", "rain", "cassie", "kai"}  # owner, 2026-11-25
ENGINE_DIRS = {"OmniVoice": "models/omnivoice-runtime/checkpoints",
               "Fish S2 Pro": "models/audio-cpp/Fish-Audio-S2-Pro-GGUF"}


def slug(name):
    return name.lower().replace(" ", "_")


def cmd_discover(args):
    from cast_discovery import discover
    rows = discover(str(DB), args.projects, args.min_chapter, top=args.top)
    for row in rows:
        mark = "voiced" if row["voiced"] else "NEEDS A VOICE"
        print(f"{row['name']:24} ~{row['est_dialogue'] + row['lines_labelled']:5} lines  "
              f"{row['chapters']:3} chapters  from {row['first_chapter']}  {row['gender']:7}  {mark}")


def cmd_screen(args):
    import sqlite3
    from casting import alias_chain
    from voice_screening import Screener, screen_candidates
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    screener = Screener(dict(con.execute("select speaker, ref_audio_path from voices")))
    for name in args.names:
        results = screen_candidates(screener, DESIGN / slug(name), own_names=set(alias_chain(name)))
        for cand, r in results.items():
            verdict = "pass" if r["passed"] else "FAIL"
            print(f"{name:26} {cand:8} {verdict}  words {r['words']:.2f}  f0 {r['f0_hz']} Hz "
                  f"({r['expected'] or 'any'})  nearest {r['nearest']} {r['similarity']:.2f}")


def decode(votes, key):
    """Picks -> {character: {voice, engine, reference}} using the round's private key."""
    if key.get("pack") != votes.get("pack"):
        raise SystemExit(f"Votes are for pack {votes.get('pack')}, key is for {key.get('pack')}")
    characters = key.get("characters") or {}
    decided = {}
    for character, entry in votes.get("picks", {}).items():
        pick = entry.get("pick", "")
        table = characters.get(character) or (key.get("takes") if "takes" in key else None)
        if not pick or pick == "none" or not table or pick not in table:
            continue
        decided[character] = {**table[pick], "notes": entry.get("notes", "")}
    return decided


def apply_votes(votes, key, sm, profile_path=PROFILE, editions=EDITIONS, decisions_path=DECISIONS):
    from casting import choose_voice, voice_path
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    actors = profile.setdefault("actors", {})
    log = json.loads(Path(decisions_path).read_text(encoding="utf-8")) if Path(decisions_path).is_file() else []
    voices = sm.get_voice_map()
    applied = []
    for character, choice in decode(votes, key).items():
        actor = choose_voice(character, "neutral", voices).canonical
        previous = voice_path(voices[character]) if character in voices else None
        reference = Path(choice["reference"])
        if choice["voice"] != "current":
            if character.casefold() in PROTECTED:
                raise SystemExit(f"{character} is protected; its voice is never replaced")
            meta = reference.with_suffix(".json")
            target = Path(editions) / f"{slug(character)}-{choice['voice']}-{votes['pack'][:6]}{reference.suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(reference, target)
            if meta.is_file():
                script = json.loads(meta.read_text(encoding="utf-8")).get("reference_script", "")
                target.with_suffix(".txt").write_text(script.strip() + "\n", encoding="utf-8")
            sm.set_voice(character, str(target))
            reference = target
        engine_dir = ENGINE_DIRS.get(choice["engine"])
        if engine_dir and engine_dir != profile.get("characters"):
            actors[actor] = engine_dir
        else:
            actors.pop(actor, None)  # the default character engine needs no override
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pack": votes["pack"],
                 "character": character, "actor": actor, "voice": choice["voice"], "engine": choice["engine"],
                 "reference": str(reference), "previous": previous, "notes": choice.get("notes", "")}
        log.append(entry)
        applied.append(entry)
    Path(profile_path).write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(decisions_path).write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return applied


def cmd_apply(args):
    from state_manager import StateManager
    votes = json.loads(Path(args.votes).read_text(encoding="utf-8"))
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    for entry in apply_votes(votes, key, StateManager(str(DB))):
        print(f"{entry['character']:24} -> {entry['voice']:10} on {entry['engine']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover", help="Rank speakers and show who still needs a voice")
    d.add_argument("--projects", type=int, nargs="+", required=True)
    d.add_argument("--min-chapter", type=int)
    d.add_argument("--top", type=int, default=40)
    s = sub.add_parser("screen", help="Check designed candidates for wrong words, pitch or duplicate voices")
    s.add_argument("names", nargs="+")
    a = sub.add_parser("apply", help="Register the owner's picks from a casting page")
    a.add_argument("votes")
    a.add_argument("key")
    args = parser.parse_args(argv)
    {"discover": cmd_discover, "screen": cmd_screen, "apply": cmd_apply}[args.command](args)


if __name__ == "__main__":
    main()
