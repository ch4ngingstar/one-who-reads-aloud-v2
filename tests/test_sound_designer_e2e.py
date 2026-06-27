"""
E2E integration test for SoundDesigner — REAL FFmpeg, no monkeypatching.
====================================================================
The unit tests in test_sound_designer.py monkeypatch ``_run``, so the actual
``filter_complex`` graph is never executed by FFmpeg. This test closes that gap:
it synthesises a voice bus + one clip of each cue kind (ambience / music / sfx),
runs the real two-pass mix, and proves the graph is valid FFmpeg — i.e. the mix
path succeeded and we did NOT silently fall back to the plain voice encode.

Requires FFmpeg in PATH (same hard dependency as production). Skips cleanly if
FFmpeg is unavailable so it never breaks a no-FFmpeg CI box.
"""

import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sound_designer import SoundDesigner  # noqa: E402

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None
SR = 44100


def _gen(cmd: list) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"fixture gen failed:\n{r.stderr[-800:]}")


def _make_tone(path: Path, freq: int, dur: float, vol: float = 0.6) -> None:
    """Synthesise a stereo WAV tone (PCM 16-bit, 44.1 kHz)."""
    _gen([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={dur}:sample_rate={SR}",
        "-af", f"volume={vol}", "-ac", "2", "-c:a", "pcm_s16le", str(path),
    ])


def _make_noise(path: Path, dur: float) -> None:
    """Synthesise a stereo noise bed (ambience surrogate)."""
    _gen([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anoisesrc=duration={dur}:sample_rate={SR}:amplitude=0.3",
        "-ac", "2", "-c:a", "pcm_s16le", str(path),
    ])


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _wav_frames(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        return wf.readframes(wf.getnframes())


def _build_fixtures(d: Path) -> dict:
    voice = d / "voice_bus.wav"
    _make_tone(voice, freq=200, dur=6.0, vol=0.7)   # the "voice" key signal
    amb = d / "amb_rain.wav"
    _make_noise(amb, dur=2.0)                        # short loopable bed
    mus = d / "mus_dread.wav"
    _make_tone(mus, freq=110, dur=4.0, vol=0.5)      # music swell source
    sfx = d / "sfx_clang.wav"
    _make_tone(sfx, freq=880, dur=0.4, vol=0.8)      # one-shot
    return {"voice": voice, "amb": amb, "mus": mus, "sfx": sfx}


def test_render_mixes_all_kinds_with_real_ffmpeg():
    if not _HAVE_FFMPEG:
        print("  SKIP test_render_mixes_all_kinds_with_real_ffmpeg (no ffmpeg)")
        return
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fx = _build_fixtures(d)
        voice_s = _wav_seconds(fx["voice"])

        sd = SoundDesigner({"output_format": "wav"})
        resolved = [
            {"kind": "ambience", "path": fx["amb"], "loopable": True,
             "start_ms": 0, "dur_s": 5.5, "gain_db": -22.0},
            {"kind": "music", "path": fx["mus"],
             "at_ms": 500, "dur_s": 3.0, "gain_db": -20.0},
            {"kind": "sfx", "path": fx["sfx"], "at_ms": 2000, "gain_db": -14.0},
        ]

        # 1) The real filter graph must be valid FFmpeg on its own — run the exact
        #    mix command directly so a graph error surfaces instead of being
        #    masked by render()'s plain-voice fallback.
        inputs, graph = sd.build_filter_complex(resolved, n_channels=2)
        cmd = ["ffmpeg", "-y", "-i", str(fx["voice"])]
        for inp in inputs:
            cmd += inp
        cmd += ["-filter_complex", graph, "-map", "[mix]",
                "-ar", str(SR), "-ac", "2", str(d / "direct_mix.wav")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, f"filter_complex rejected by ffmpeg:\n{r.stderr[-1200:]}"
        assert (d / "direct_mix.wav").exists()

        # 2) render() end-to-end produces a real mixed file (not the fallback).
        out = d / "chapter_mix.wav"
        result = sd.render(fx["voice"], resolved, out, n_channels=2)
        assert Path(result).exists()
        assert out.stat().st_size >= 4096

        # 3) The mix preserves the voice-bus duration (beds are delayed/trimmed
        #    inside it, never extend it) — a sanity check that we layered under
        #    the voice rather than concatenating.
        out_s = _wav_seconds(out)
        assert abs(out_s - voice_s) < 0.5, f"duration drift: voice={voice_s}s mix={out_s}s"

        # 4) The mix must differ in PCM CONTENT from a plain encode of the voice
        #    bus — proves cues were actually layered, not silently dropped.
        #    (Byte SIZE is identical for same-duration PCM WAV, so compare frames.)
        plain = d / "plain.wav"
        sd._encode_plain(fx["voice"], plain, n_channels=2)
        assert _wav_frames(out) != _wav_frames(plain), \
            "mixed output identical in content to plain voice — cues did not layer"

        print("  PASS test_render_mixes_all_kinds_with_real_ffmpeg")


def test_resolve_then_render_from_cue_rows():
    """Exercise resolve_cues (DB-row shape) -> render with real FFmpeg."""
    if not _HAVE_FFMPEG:
        print("  SKIP test_resolve_then_render_from_cue_rows (no ffmpeg)")
        return
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fx = _build_fixtures(d)

        # A two-line timeline matching what AudioAssembler would compute.
        timeline = {0: (0.0, 3000.0), 1: (3200.0, 6000.0)}
        sfx_map = {
            "rain_soft":   {"path": str(fx["amb"]), "loopable": True},
            "dread_swell": {"path": str(fx["mus"])},
            "sword_clang": {"path": str(fx["sfx"])},
        }
        cues = [
            {"cue_type": "scene", "tag": "rain_soft", "line_start": 0,
             "line_end": 1, "gain_db": -22},
            {"cue_type": "music", "tag": "dread_swell", "line_start": 1,
             "duration_s": 3, "gain_db": -20},
            {"cue_type": "sfx", "tag": "sword_clang", "line_start": 0,
             "at_anchor": "end", "gain_db": -14},
            # Unknown tag must be dropped, never crash the render.
            {"cue_type": "sfx", "tag": "does_not_exist", "line_start": 0,
             "at_anchor": "start", "gain_db": -10},
        ]

        sd = SoundDesigner({"output_format": "wav"})
        resolved = sd.resolve_cues(cues, sfx_map, timeline)
        assert len(resolved) == 3, f"expected 3 resolved cues, got {len(resolved)}"

        out = d / "from_rows.wav"
        result = sd.render(fx["voice"], resolved, out, n_channels=2)
        assert Path(result).exists() and out.stat().st_size >= 4096
        print("  PASS test_resolve_then_render_from_cue_rows")


TESTS = [
    test_render_mixes_all_kinds_with_real_ffmpeg,
    test_resolve_then_render_from_cue_rows,
]

if __name__ == "__main__":
    for t in TESTS:
        t()
    print("\nAll SoundDesigner E2E tests passed.")
