"""
Test suite for Module 5b: sound_designer.py
Run: python tests/test_sound_designer.py

No FFmpeg required — SoundDesigner._run is monkeypatched. build_timeline is
tested with real WAVs; build_filter_complex/resolve_cues are pure.
"""

import sys
import wave
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sound_designer import SoundDesigner


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_real_wav(path: Path, duration_ms: int = 100, sample_rate: int = 22050) -> Path:
    n_frames = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return path


# ── build_timeline ────────────────────────────────────────────────────────────

def test_build_timeline_exact_offsets_with_speaker_gap():
    with tempfile.TemporaryDirectory() as tmp:
        w0 = _make_real_wav(Path(tmp) / "line_0000.wav", duration_ms=100)
        w1 = _make_real_wav(Path(tmp) / "line_0001.wav", duration_ms=100)
        lines = [
            {"line_index": 0, "speaker": "Narrator", "audio_path": str(w0)},
            {"line_index": 1, "speaker": "Sunny",    "audio_path": str(w1)},
        ]
        sd = SoundDesigner()
        timeline, total = sd.build_timeline(lines, inter_line_silence_ms=200,
                                            inter_speaker_silence_ms=380)
        # line0: 0..100ms. gap is a speaker change (380). line1: 480..580ms.
        assert timeline[0] == (0.0, 100.0), timeline[0]
        assert timeline[1] == (480.0, 580.0), timeline[1]
        assert total == 580.0
    print("  PASS test_build_timeline_exact_offsets_with_speaker_gap")


def test_build_timeline_same_speaker_short_gap():
    with tempfile.TemporaryDirectory() as tmp:
        w0 = _make_real_wav(Path(tmp) / "a.wav", duration_ms=100)
        w1 = _make_real_wav(Path(tmp) / "b.wav", duration_ms=100)
        lines = [
            {"line_index": 0, "speaker": "Narrator", "audio_path": str(w0)},
            {"line_index": 1, "speaker": "Narrator", "audio_path": str(w1)},
        ]
        sd = SoundDesigner()
        timeline, _ = sd.build_timeline(lines, 200, 380)
        # same speaker -> short 200ms gap: line1 starts at 300ms.
        assert timeline[1] == (300.0, 400.0), timeline[1]
    print("  PASS test_build_timeline_same_speaker_short_gap")


def test_build_timeline_omits_unsynthesised_line():
    with tempfile.TemporaryDirectory() as tmp:
        w0 = _make_real_wav(Path(tmp) / "a.wav", duration_ms=100)
        # only line 0 and line 2 were synthesised (line 1 failed, absent here)
        w2 = _make_real_wav(Path(tmp) / "c.wav", duration_ms=100)
        lines = [
            {"line_index": 0, "speaker": "Narrator", "audio_path": str(w0)},
            {"line_index": 2, "speaker": "Narrator", "audio_path": str(w2)},
        ]
        sd = SoundDesigner()
        timeline, _ = sd.build_timeline(lines, 200, 380)
        assert 1 not in timeline
        assert set(timeline.keys()) == {0, 2}
    print("  PASS test_build_timeline_omits_unsynthesised_line")


# ── resolve_cues ──────────────────────────────────────────────────────────────

def _sfx_map(tmp: Path):
    amb = _make_real_wav(tmp / "amb.wav")
    sfx = _make_real_wav(tmp / "clash.wav")
    mus = _make_real_wav(tmp / "drone.wav")
    return {
        "cold_rain":    {"path": str(amb), "category": "ambience", "loopable": True},
        "sword_clash":  {"path": str(sfx), "category": "sfx",      "loopable": False},
        "dread_drone":  {"path": str(mus), "category": "music",    "loopable": True},
    }


def test_resolve_cues_happy_path_orders_and_anchors():
    with tempfile.TemporaryDirectory() as tmp:
        sfx_map = _sfx_map(Path(tmp))
        timeline = {0: (0.0, 100.0), 1: (300.0, 400.0), 2: (600.0, 700.0)}
        cues = [
            {"cue_type": "sfx", "tag": "sword_clash", "line_start": 1,
             "at_anchor": "end", "gain_db": -12.0},
            {"cue_type": "scene", "tag": "cold_rain", "line_start": 0,
             "line_end": 2, "gain_db": -22.0},
            {"cue_type": "music", "tag": "dread_drone", "line_start": 0,
             "duration_s": 8.0, "gain_db": -20.0},
        ]
        sd = SoundDesigner()
        resolved = sd.resolve_cues(cues, sfx_map, timeline)
        kinds = [r["kind"] for r in resolved]
        assert kinds == ["ambience", "music", "sfx"], kinds   # input order
        scene = resolved[0]
        assert scene["start_ms"] == 0 and abs(scene["dur_s"] - 0.7) < 1e-6
        sfx = resolved[2]
        assert sfx["at_ms"] == 400   # 'end' anchor of line 1
    print("  PASS test_resolve_cues_happy_path_orders_and_anchors")


def test_resolve_cues_drops_unknown_tag_and_missing_line():
    with tempfile.TemporaryDirectory() as tmp:
        sfx_map = _sfx_map(Path(tmp))
        timeline = {0: (0.0, 100.0)}
        cues = [
            {"cue_type": "scene", "tag": "no_such_sound", "line_start": 0, "line_end": 0},
            {"cue_type": "sfx", "tag": "sword_clash", "line_start": 5},   # line not in timeline
            {"cue_type": "scene", "tag": "cold_rain", "line_start": 0, "line_end": 0},
        ]
        sd = SoundDesigner()
        resolved = sd.resolve_cues(cues, sfx_map, timeline)
        assert len(resolved) == 1
        assert resolved[0]["kind"] == "ambience"
    print("  PASS test_resolve_cues_drops_unknown_tag_and_missing_line")


def test_resolve_cues_alias_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        sfx_map = _sfx_map(Path(tmp))
        timeline = {0: (0.0, 100.0)}
        cues = [{"cue_type": "scene", "tag": "rain", "line_start": 0, "line_end": 0}]
        sd = SoundDesigner()
        resolved = sd.resolve_cues(cues, sfx_map, timeline,
                                   alias_map={"rain": "cold_rain"})
        assert len(resolved) == 1 and resolved[0]["kind"] == "ambience"
    print("  PASS test_resolve_cues_alias_resolution")


def test_resolve_cues_clamps_gain():
    with tempfile.TemporaryDirectory() as tmp:
        sfx_map = _sfx_map(Path(tmp))
        timeline = {0: (0.0, 100.0)}
        cues = [{"cue_type": "sfx", "tag": "sword_clash", "line_start": 0, "gain_db": 50.0}]
        sd = SoundDesigner()
        resolved = sd.resolve_cues(cues, sfx_map, timeline)
        assert resolved[0]["gain_db"] == 0.0   # clamped to [-40, 0]
    print("  PASS test_resolve_cues_clamps_gain")


# ── build_filter_complex ──────────────────────────────────────────────────────

def _resolved_all():
    return [
        {"kind": "ambience", "path": Path("/sfx/amb.wav"), "loopable": True,
         "start_ms": 0, "dur_s": 0.7, "gain_db": -22.0},
        {"kind": "music", "path": Path("/sfx/drone.wav"),
         "at_ms": 0, "dur_s": 8.0, "gain_db": -20.0},
        {"kind": "sfx", "path": Path("/sfx/clash.wav"),
         "at_ms": 400, "gain_db": -12.0},
    ]


def test_build_filter_complex_full_graph():
    sd = SoundDesigner()
    inputs, graph = sd.build_filter_complex(_resolved_all(), n_channels=2)

    assert len(inputs) == 3
    # ambience clip is looped to fill the scene
    assert inputs[0][:2] == ["-stream_loop", "-1"], inputs[0]
    # core graph features
    assert "sidechaincompress" in graph
    assert "asplit=2[vmain][vkey]" in graph
    assert "alimiter=limit=" in graph
    assert "afade=t=in" in graph
    assert "volume=-22.0dB" in graph
    # ambience + music form the ducked bed (2 inputs), normalize must be off
    assert "amix=inputs=2:normalize=0[bedraw]" in graph
    assert "normalize=0" in graph and "normalize=1" not in graph
    # stereo adelay carries one value per channel
    assert "adelay=0|0" in graph
    assert "adelay=400|400" in graph
    # final mix sums voice + bed + sfx
    assert "amix=inputs=3:normalize=0[premix]" in graph
    print("  PASS test_build_filter_complex_full_graph")


def test_build_filter_complex_no_ambience_omits_sidechain():
    sd = SoundDesigner()
    resolved = [{"kind": "sfx", "path": Path("/sfx/clash.wav"),
                 "at_ms": 100, "gain_db": -12.0}]
    inputs, graph = sd.build_filter_complex(resolved, n_channels=2)
    assert "sidechaincompress" not in graph
    assert "asplit" not in graph
    # voice [0:a] + sfx bus -> 2-input final mix
    assert "amix=inputs=2:normalize=0[premix]" in graph
    assert "[sfxbus]" in graph
    print("  PASS test_build_filter_complex_no_ambience_omits_sidechain")


def test_build_filter_complex_mono_adelay_single_value():
    sd = SoundDesigner()
    resolved = [{"kind": "sfx", "path": Path("/sfx/clash.wav"),
                 "at_ms": 250, "gain_db": -12.0}]
    _, graph = sd.build_filter_complex(resolved, n_channels=1)
    assert "adelay=250[" in graph   # single channel -> single delay value
    assert "channel_layouts=mono" in graph
    print("  PASS test_build_filter_complex_mono_adelay_single_value")


# ── render (monkeypatched ffmpeg) ─────────────────────────────────────────────

def test_render_no_cues_encodes_plain():
    with tempfile.TemporaryDirectory() as tmp:
        voice = _make_real_wav(Path(tmp) / "voice.wav")
        out = Path(tmp) / "ch.mp3"
        captured = []

        sd = SoundDesigner()
        def fake_run(cmd):
            captured.append(cmd)
            out.write_bytes(b"X" * 5000)
        sd._run = fake_run

        result = sd.render(voice, [], out, n_channels=2)
        assert result == str(out)
        # plain encode: no filter graph
        assert "-filter_complex" not in captured[0]
        assert str(voice) in captured[0]
    print("  PASS test_render_no_cues_encodes_plain")


def test_render_falls_back_when_mix_fails():
    with tempfile.TemporaryDirectory() as tmp:
        voice = _make_real_wav(Path(tmp) / "voice.wav")
        out = Path(tmp) / "ch.mp3"
        calls = []

        sd = SoundDesigner()
        def fake_run(cmd):
            calls.append(cmd)
            if "-filter_complex" in cmd:          # the mix pass fails
                raise RuntimeError("boom")
            out.write_bytes(b"X" * 5000)           # the plain fallback succeeds

        sd._run = fake_run
        resolved = _resolved_all()
        result = sd.render(voice, resolved, out, n_channels=2)

        assert result == str(out)
        assert out.exists()
        # first call attempted the mix, second was the plain fallback
        assert "-filter_complex" in calls[0]
        assert "-filter_complex" not in calls[1]
    print("  PASS test_render_falls_back_when_mix_fails")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_build_timeline_exact_offsets_with_speaker_gap,
    test_build_timeline_same_speaker_short_gap,
    test_build_timeline_omits_unsynthesised_line,
    test_resolve_cues_happy_path_orders_and_anchors,
    test_resolve_cues_drops_unknown_tag_and_missing_line,
    test_resolve_cues_alias_resolution,
    test_resolve_cues_clamps_gain,
    test_build_filter_complex_full_graph,
    test_build_filter_complex_no_ambience_omits_sidechain,
    test_build_filter_complex_mono_adelay_single_value,
    test_render_no_cues_encodes_plain,
    test_render_falls_back_when_mix_fails,
]

if __name__ == "__main__":
    print("Running Module 5b tests...\n")
    passed, failed = 0, 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
