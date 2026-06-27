"""Drive the SoundDesigner end-to-end with REAL ffmpeg and produce a playable mix.

Uses the ear-confirmed ch_0267 demo line WAVs as the voice bus, synthesises
stand-in ambience/music/sfx clips (the real CC0 library isn't sourced yet), then
layers a small cue plan over the speech and writes a persistent WAV you can open.

Run:  python scripts/demo_sound_design.py
Out:  data/sound_demo/ch0267_sounddesign.wav  (+ voice_only.wav to A/B against)
"""

import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sound_designer import SoundDesigner  # noqa: E402
from state_manager import StateManager, _resolve_stored_path  # noqa: E402

DB_PATH = ROOT / "src" / "data" / "pipeline.db"

SR = 44100
LINES_DIR = ROOT / "data" / "audio" / "ch_0267"
OUT_DIR = ROOT / "data" / "sound_demo"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _run(cmd: list) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(map(str, cmd))}\n{r.stderr[-1000:]}")


def _wav_ms(p: Path) -> float:
    with wave.open(str(p), "rb") as wf:
        return wf.getnframes() / wf.getframerate() * 1000.0


def build_voice_bus() -> tuple[Path, dict]:
    """Concat the demo line WAVs into one bus; return it + a per-line timeline."""
    lines = sorted(LINES_DIR.glob("line_*.wav"))
    if not lines:
        raise SystemExit(f"No demo line WAVs in {LINES_DIR}")
    print(f"[demo] voice bus from {len(lines)} demo lines of ch_0267")

    # Re-encode each to a uniform 44.1k stereo PCM so concat is clean, and build
    # the timeline {line_index: (start_ms, end_ms)} as AudioAssembler would.
    norm_dir = OUT_DIR / "_norm"
    norm_dir.mkdir(exist_ok=True)
    GAP_MS = 250.0
    timeline: dict[int, tuple[float, float]] = {}
    cursor = 0.0
    concat_list = norm_dir / "concat.txt"
    with concat_list.open("w", encoding="utf-8") as fh:
        for i, src in enumerate(lines):
            dst = norm_dir / f"n_{i:04d}.wav"
            _run(["ffmpeg", "-y", "-i", str(src), "-ar", str(SR), "-ac", "2",
                  "-c:a", "pcm_s16le", str(dst)])
            if i > 0:
                cursor += GAP_MS
                sil = norm_dir / f"sil_{i:04d}.wav"
                _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                      f"anullsrc=r={SR}:cl=stereo", "-t", f"{GAP_MS/1000.0}",
                      "-c:a", "pcm_s16le", str(sil)])
                fh.write(f"file '{sil.as_posix()}'\n")
            start = cursor
            cursor += _wav_ms(dst)
            timeline[i] = (start, cursor)
            fh.write(f"file '{dst.as_posix()}'\n")

    voice = OUT_DIR / "voice_only.wav"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
          "-c:a", "pcm_s16le", str(voice)])
    print(f"[demo] voice bus: {_wav_ms(voice)/1000:.1f}s -> {voice.name}")
    return voice, timeline


def synth_library() -> dict:
    """Stand-in clips for the not-yet-sourced CC0 library."""
    lib = OUT_DIR / "_clips"
    lib.mkdir(exist_ok=True)
    rain = lib / "rain_soft.wav"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
          f"anoisesrc=duration=3:sample_rate={SR}:amplitude=0.25:color=pink",
          "-ac", "2", "-c:a", "pcm_s16le", str(rain)])
    dread = lib / "dread_swell.wav"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
          f"sine=frequency=72:duration=6:sample_rate={SR}",
          "-af", "tremolo=f=0.4:d=0.6,volume=0.5", "-ac", "2",
          "-c:a", "pcm_s16le", str(dread)])
    clang = lib / "sword_clang.wav"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i",
          f"sine=frequency=1200:duration=0.35:sample_rate={SR}",
          "-af", "volume=0.8,afade=t=out:st=0.05:d=0.3", "-ac", "2",
          "-c:a", "pcm_s16le", str(clang)])
    return {
        "rain_soft":   {"path": str(rain), "loopable": True},
        "dread_swell": {"path": str(dread)},
        "sword_clang": {"path": str(clang)},
    }


def real_library() -> dict:
    """Load the registered (ElevenLabs-generated) clips from the live DB.

    Mirrors the production path: AudioAssembler reads StateManager.get_sfx_map()
    and feeds it to SoundDesigner.resolve_cues. Only clips whose file exists on
    disk are kept, so a partially-built library still renders.
    """
    sm = StateManager(str(DB_PATH))
    sfx_map = {}
    for tag, asset in sm.get_sfx_map().items():
        if _resolve_stored_path(asset["path"]).exists():
            sfx_map[tag] = asset
    print(f"[demo] real library: {sorted(sfx_map)}")
    return sfx_map


def main() -> None:
    voice, timeline = build_voice_bus()
    sfx_map = real_library()
    last_line = max(timeline)

    # A cinematic cue plan over the speech, using the REAL generated tags.
    # Gains are LOUD on purpose for this audibility demo — the shipped defaults
    # (-22/-20/-14) are too subtle for clips recorded at moderate level.
    # 2026-06-27: user wanted the layer ~15-20% louder -> +1.5 dB on every cue
    # (+1.5 dB ~= +18.8% amplitude), keeping the relative balance intact.
    cues = [
        # Cues authored to the ACTUAL text of ch_1854 "The Shadow's Response":
        # a war council in a stone chamber. Each cue maps to a specific moment.
        # Setting: a stone council chamber -> faint hollow room tone (NOT rain).
        {"cue_type": "scene", "tag": "ruined_halls", "line_start": 0,
         "line_end": last_line, "gain_db": -21.5},
        # Mood: the Lord of Shadows' cold menace -> a low dread drone enters as he
        # begins his dark address (line 5) and underscores it.
        {"cue_type": "music", "tag": "dread_low_drone", "line_start": min(5, last_line),
         "duration_s": 16, "gain_db": -19.5},
        # Event (line 7): "shadows crawled... like a stream of darkness... manifested"
        # -> the signature shadow-conjuring moment. Audible because it's diegetic.
        {"cue_type": "sfx", "tag": "shadow_whoosh", "line_start": min(7, last_line),
         "at_anchor": "start", "gain_db": -8.5},
        # Event (line 9): "a wave of whispers in the stone chamber" -> the council
        # reacts. A brief, soft collective murmur.
        {"cue_type": "sfx", "tag": "crowd_gasp", "line_start": min(9, last_line),
         "at_anchor": "start", "gain_db": -14.5},
    ]
    # Drop any cue whose tag wasn't generated yet, so the demo runs with whatever
    # slice of the library exists.
    cues = [c for c in cues if c["tag"] in sfx_map]

    # Ease the ducking so beds stay clearly present under speech (gentler ratio,
    # higher threshold) instead of being pumped to silence by continuous narration.
    sd = SoundDesigner({
        "output_format": "wav",
        "duck_threshold": 0.15,
        "duck_ratio": 3,
        "duck_release": 250,
        "duck_makeup": 1,
    })
    resolved = sd.resolve_cues(cues, sfx_map, timeline)
    print(f"[demo] {len(resolved)} of {len(cues)} cues resolved + render-ready")

    out = OUT_DIR / "ch0267_sounddesign.wav"
    sd.render(voice, resolved, out, n_channels=2)
    print("\n=== RESULT ===")
    print(f"  voice-only : {voice}")
    print(f"  with sound : {out}   ({out.stat().st_size/1024:.0f} KB, "
          f"{_wav_ms(out)/1000:.1f}s)")
    print("  A/B these two files to judge the mix.")


if __name__ == "__main__":
    main()
