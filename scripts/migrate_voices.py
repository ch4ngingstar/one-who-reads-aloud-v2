"""One-off voice library cleanup + import.

- Renames every registered voice clip to a simple lowercase name.
- Imports new/upgraded clips from the "new old voices" desktop folder
  (mp3 -> wav via ffmpeg; wav copied as-is).
- Registers the 5 previously-clipless Shadow Slave characters
  (Jest, Seishan, Helie, Moonveil, Warden) + Rein.
- Archives the old prefixed files instead of deleting them.

Run with --apply to actually perform changes; default is a dry run.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "src", "data", "pipeline.db")
VOICES = os.path.join(ROOT, "src", "data", "voices")
NEWFOLDER = r"C:\Users\alityan\OneDrive\Desktop\new old voices"
ARCHIVE = os.path.join(VOICES, "_archive_old")

APPLY = "--apply" in sys.argv

# canonical speaker -> simple base filename (no extension)
SIMPLE = {
    "Narrator": "narrator", "_default": "narrator",
    "Aiko": "aiko", "Asterion": "asterion", "Beastmaster": "beastmaster",
    "Cassie": "cassie", "Effie": "effie", "Eurys Of The Nine": "eurys",
    "Fleur": "fleur", "Instructor Ram": "instructor_ram",
    "Julius": "instructor_ram", "Teacher Julius": "instructor_ram",
    "Jet": "jet", "Kai": "kai", "Kim": "kim", "Lord Valor": "valor",
    "Luster": "luster", "Mordret": "mordret", "Morgan": "morgan",
    "Nephis": "nephis", "Queen Ki Song": "ki_song", "Rain": "rain",
    "Ray": "ray", "Revel Of Song": "revel", "Roan": "roan",
    "Saint Bloodwave": "bloodwave", "Saint Naeve": "naeve", "Sunny": "sunny",
    "Tamar Of Sorrow": "tamar", "The Bureaucrat": "bureaucrat",
    "The Dream Realm Wanderer": "dream_wanderer",
    "The Hardened Awakened": "hardened_awakened",
    "The Legacy Noble": "legacy_noble",
    "The Nightmare Abomination": "abomination",
    "The Nightmare Spell": "nightmare_spell", "Tyris": "tyris",
    # new characters
    "Jest": "jest", "Seishan": "seishan", "Helie": "helie",
    "Moonveil": "moonveil", "Warden": "warden", "Rein": "rein",
}

# canonical -> source file inside NEWFOLDER (upgrades + brand-new chars)
FROM_NEW = {
    "Aiko": "aiko.mp3", "Beastmaster": "beastmaste.mp3",
    "Cassie": "raw_Cassie.wav", "Effie": "Effie.wav",
    "Instructor Ram": "instructor ram.mp3", "Queen Ki Song": "queen ki song.wav",
    "Sunny": "sunny.wav", "The Nightmare Spell": "the spell.mp3",
    "Rein": "rein.mp3",
    "Jest": "voice_preview_jest.mp3", "Seishan": "voice_preview_seishan.mp3",
    "Helie": "voice_preview_helie.mp3", "Moonveil": "voice_preview_moonveil.mp3",
    "Warden": "voice_preview_warden.mp3",
}

# speakers that need a source not in the current DB row nor in NEWFOLDER
FALLBACK_SRC = {
    "Jet": os.path.join(VOICES, "voice_preview_jet.wav"),
}


def to_wav(src: str, dst: str) -> None:
    """Copy wav as-is, or transcode anything else to mono wav via ffmpeg."""
    if src.lower().endswith(".wav"):
        if APPLY:
            shutil.copyfile(src, dst)
        return
    if APPLY:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", dst],
            check=True,
        )


def main() -> None:
    con = sqlite3.connect(DB)
    rows = dict(con.execute("SELECT speaker, ref_audio_path FROM voices"))

    # union of existing speakers + new characters
    speakers = sorted(set(rows) | set(SIMPLE))
    plan = []  # (speaker, source, target_simple_wav)
    problems = []

    for spk in speakers:
        if spk not in SIMPLE:
            problems.append(f"no simple-name rule for '{spk}'")
            continue
        target = os.path.join(VOICES, SIMPLE[spk] + ".wav")

        if spk in FROM_NEW:
            src = os.path.join(NEWFOLDER, FROM_NEW[spk])
        elif spk in FALLBACK_SRC:
            src = FALLBACK_SRC[spk]
        elif spk in rows and os.path.exists(rows[spk]):
            src = rows[spk]
        else:
            # shared-file speakers (Julius etc.) resolve to an already-built target
            if os.path.basename(target) in {
                os.path.basename(os.path.join(VOICES, SIMPLE[s] + ".wav"))
                for s in FROM_NEW
            } or spk in ("Julius", "Teacher Julius", "_default"):
                plan.append((spk, "(shared target)", target))
                continue
            problems.append(f"no source for '{spk}' (db={rows.get(spk)!r})")
            continue
        if not os.path.exists(src):
            problems.append(f"source missing for '{spk}': {src}")
            continue
        plan.append((spk, src, target))

    print(f"=== VOICE MIGRATION {'(APPLY)' if APPLY else '(DRY RUN)'} ===\n")
    for spk, src, target in plan:
        tag = "NEW " if spk in ("Jest", "Seishan", "Helie", "Moonveil",
                                 "Warden", "Rein") else "    "
        up = "UPGRADE" if spk in FROM_NEW and spk not in (
            "Jest", "Seishan", "Helie", "Moonveil", "Warden", "Rein") else ""
        srcname = src if src == "(shared target)" else os.path.basename(src)
        print(f"{tag}{spk:24s} <- {srcname:45s} => {os.path.basename(target)} {up}")

    if problems:
        print("\n!!! PROBLEMS:")
        for p in problems:
            print("  - " + p)

    if not APPLY:
        print("\n(dry run — pass --apply to execute)")
        return

    # back up DB
    bak = DB + ".bak-voices"
    shutil.copyfile(DB, bak)
    print(f"\nDB backed up -> {bak}")

    # build all target wavs (once per target; owners sort before sharers, so an
    # UPGRADE source wins over a speaker that merely shares the same clip)
    built: set[str] = set()
    for spk, src, target in plan:
        if src == "(shared target)" or target in built:
            continue
        to_wav(src, target)
        built.add(target)

    # update DB (canonical speaker keys unchanged; only paths)
    for spk, src, target in plan:
        con.execute(
            "INSERT INTO voices(speaker, ref_audio_path) VALUES(?,?) "
            "ON CONFLICT(speaker) DO UPDATE SET ref_audio_path=excluded.ref_audio_path",
            (spk, target),
        )
    con.commit()

    # archive old prefixed files (anything not a current simple target)
    keep = {os.path.basename(t) for _, _, t in plan}
    os.makedirs(ARCHIVE, exist_ok=True)
    archived = 0
    for f in os.listdir(VOICES):
        fp = os.path.join(VOICES, f)
        if os.path.isfile(fp) and f not in keep:
            shutil.move(fp, os.path.join(ARCHIVE, f))
            archived += 1
    print(f"archived {archived} old files -> {ARCHIVE}")

    # verify
    bad = [(s, p) for s, p in con.execute("SELECT speaker, ref_audio_path FROM voices")
           if not os.path.exists(p)]
    print("\nVERIFY:", "all voice paths exist ✔" if not bad else f"MISSING: {bad}")
    con.close()


if __name__ == "__main__":
    main()
