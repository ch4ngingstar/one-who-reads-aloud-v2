"""
Test suite for sound-design cue I/O (cue_io.py).
Run: python tests/test_cue_io.py
No GPU / no model / no FFmpeg required.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
import diarization_io as dio
import cue_io


def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_chapter(sm, text_chunks):
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 7,
            "title": "Chapter 7",
            "chunks": [
                {"chunk_index": i, "text": t, "word_count": len(t.split())}
                for i, t in enumerate(text_chunks)
            ],
        }],
    }
    pid = sm.seed_project(book)
    return sm.get_all_chapters(pid)[0]["id"]


# ── validate_cues ─────────────────────────────────────────────────────────────

def test_validate_cues_happy_path():
    payload = {"sound_design": {
        "scenes": [{"line_start": 0, "line_end": 5, "ambience_tag": "cold_rain", "gain_db": -22}],
        "sfx": [{"line_index": 3, "at": "end", "sfx_tag": "sword_clash", "gain_db": -12}],
        "music": [{"line_index": 0, "music_tag": "dread_low_drone", "gain_db": -20, "duration_s": 8}],
    }}
    cues = cue_io.validate_cues(payload, n_segments=10)
    assert len(cues) == 3
    scene = next(c for c in cues if c["cue_type"] == "scene")
    assert scene["tag"] == "cold_rain" and scene["line_end"] == 5
    sfx = next(c for c in cues if c["cue_type"] == "sfx")
    assert sfx["at_anchor"] == "end"
    music = next(c for c in cues if c["cue_type"] == "music")
    assert music["duration_s"] == 8.0
    print("  PASS test_validate_cues_happy_path")


def test_validate_cues_accepts_bare_sound_design():
    # payload without the wrapper key still works
    payload = {"scenes": [{"line_start": 0, "line_end": 2, "ambience_tag": "forest_night"}]}
    cues = cue_io.validate_cues(payload, n_segments=5)
    assert len(cues) == 1 and cues[0]["tag"] == "forest_night"
    print("  PASS test_validate_cues_accepts_bare_sound_design")


def test_validate_cues_drops_out_of_range_and_inverted():
    payload = {"sound_design": {
        "scenes": [
            {"line_start": 0, "line_end": 100, "ambience_tag": "cold_rain"},   # out of range
            {"line_start": 4, "line_end": 2, "ambience_tag": "forest_night"},  # inverted
            {"line_start": 1, "line_end": 3, "ambience_tag": "dungeon_drip"},  # ok
        ],
        "sfx": [{"line_index": 99, "sfx_tag": "door_creak"}],                   # out of range
    }}
    cues = cue_io.validate_cues(payload, n_segments=10)
    assert len(cues) == 1
    assert cues[0]["tag"] == "dungeon_drip"
    print("  PASS test_validate_cues_drops_out_of_range_and_inverted")


def test_validate_cues_coalesces_overlapping_scenes():
    payload = {"sound_design": {"scenes": [
        {"line_start": 0, "line_end": 5, "ambience_tag": "cold_rain"},
        {"line_start": 3, "line_end": 8, "ambience_tag": "forest_night"},   # overlaps -> dropped
        {"line_start": 6, "line_end": 9, "ambience_tag": "dungeon_drip"},   # also overlaps first? no, ok
    ]}}
    cues = cue_io.validate_cues(payload, n_segments=12)
    tags = [c["tag"] for c in cues]
    # first accepted (0-5); 3-8 overlaps it -> dropped; 6-9 does not overlap 0-5 -> kept
    assert tags == ["cold_rain", "dungeon_drip"], tags
    print("  PASS test_validate_cues_coalesces_overlapping_scenes")


def test_validate_cues_clamps_gain_and_duration():
    payload = {"sound_design": {
        "scenes": [{"line_start": 0, "line_end": 1, "ambience_tag": "cold_rain", "gain_db": 50}],
        "music": [{"line_index": 0, "music_tag": "tension_rise", "duration_s": 999}],
    }}
    cues = cue_io.validate_cues(payload, n_segments=5)
    scene = next(c for c in cues if c["cue_type"] == "scene")
    music = next(c for c in cues if c["cue_type"] == "music")
    assert scene["gain_db"] == 0.0           # clamped to [-40, 0]
    assert music["duration_s"] == 20.0       # clamped to [1, 20]
    print("  PASS test_validate_cues_clamps_gain_and_duration")


def test_validate_cues_keeps_unknown_tag():
    # unknown tags are resolved/skipped at render time, not rejected here
    payload = {"sound_design": {"scenes": [
        {"line_start": 0, "line_end": 1, "ambience_tag": "totally_made_up"}]}}
    cues = cue_io.validate_cues(payload, n_segments=3)
    assert len(cues) == 1 and cues[0]["tag"] == "totally_made_up"
    print("  PASS test_validate_cues_keeps_unknown_tag")


def test_validate_cues_default_sfx_anchor():
    payload = {"sound_design": {"sfx": [
        {"line_index": 1, "sfx_tag": "door_creak"},                 # no 'at'
        {"line_index": 2, "sfx_tag": "thunder_crack", "at": "weird"},  # bad 'at'
    ]}}
    cues = cue_io.validate_cues(payload, n_segments=5)
    assert all(c["at_anchor"] == "start" for c in cues)
    print("  PASS test_validate_cues_default_sfx_anchor")


def test_validate_cues_bad_shape_raises():
    try:
        cue_io.validate_cues({"sound_design": {"scenes": "not a list"}}, n_segments=5)
        assert False, "expected ImportRejected"
    except dio.ImportRejected:
        pass
    print("  PASS test_validate_cues_bad_shape_raises")


# ── export + prompt ───────────────────────────────────────────────────────────

def test_build_cue_export_shape():
    sm = _tmp_sm()
    ch_id = _seed_chapter(sm, ['"We move at dawn." Nephis turned away.'])
    payload = cue_io.build_cue_export(sm, ch_id)
    assert payload["chapter_id"] == ch_id
    assert payload["title"] == "Chapter 7"
    assert "ambience" in payload["vocabulary"]
    assert [s["i"] for s in payload["segments"]] == list(range(len(payload["segments"])))
    assert all({"i", "text"} == set(s) for s in payload["segments"])
    print("  PASS test_build_cue_export_shape")


def test_prompt_lists_vocabulary():
    prompt = cue_io.build_cue_prompt_text()
    assert "cold_rain" in prompt and "sword_clash" in prompt and "dread_low_drone" in prompt
    assert "RESTRAINED" in prompt or "Restraint" in prompt
    print("  PASS test_prompt_lists_vocabulary")


# ── import_cues + review guard ────────────────────────────────────────────────

def test_import_cues_writes_rows():
    sm = _tmp_sm()
    ch_id = _seed_chapter(sm, ["The hall was silent. Rain fell outside."])
    n = len(dio.segment_chapter(sm, ch_id))
    payload = {"sound_design": {"scenes": [
        {"line_start": 0, "line_end": n - 1, "ambience_tag": "cold_rain", "gain_db": -22}]}}
    written = cue_io.import_cues(sm, ch_id, payload)
    assert written == 1
    cues = sm.get_cues_for_chapter(ch_id)
    assert len(cues) == 1 and cues[0]["tag"] == "cold_rain"
    print("  PASS test_import_cues_writes_rows")


def test_import_cues_review_lock_requires_force():
    sm = _tmp_sm()
    ch_id = _seed_chapter(sm, ["A line of prose here."])
    n = len(dio.segment_chapter(sm, ch_id))
    payload = {"sound_design": {"scenes": [
        {"line_start": 0, "line_end": n - 1, "ambience_tag": "forest_night"}]}}
    cue_io.import_cues(sm, ch_id, payload)
    sm.mark_cues_reviewed(ch_id, True)

    try:
        cue_io.import_cues(sm, ch_id, payload)
        assert False, "expected ImportRejected on reviewed chapter"
    except dio.ImportRejected:
        pass
    # force overrides the lock
    assert cue_io.import_cues(sm, ch_id, payload, force=True) == 1
    print("  PASS test_import_cues_review_lock_requires_force")


# ── cloud round-trip (monkeypatched provider) ─────────────────────────────────

def test_format_cues_via_cloud_parses_provider_output():
    fake_json = json.dumps({"sound_design": {
        "scenes": [{"line_start": 0, "line_end": 2, "ambience_tag": "cold_rain", "gain_db": -22}]
    }})

    def fake_call(system, user, *, api_key, model, max_tokens):
        assert "RESTRAINED" in system or "Restraint" in system
        return "Here you go:\n" + fake_json + "\nDone."

    orig = dio._PROVIDER_CALLS["claude"]
    dio._PROVIDER_CALLS["claude"] = fake_call
    try:
        export = {"segments": [{"i": 0, "text": "x"}, {"i": 1, "text": "y"}, {"i": 2, "text": "z"}]}
        out = cue_io.format_cues_via_cloud(export, provider="claude", api_key="sk-test")
        cues = cue_io.validate_cues(out, n_segments=3)
        assert len(cues) == 1 and cues[0]["tag"] == "cold_rain"
    finally:
        dio._PROVIDER_CALLS["claude"] = orig
    print("  PASS test_format_cues_via_cloud_parses_provider_output")


def test_format_cues_via_cloud_rejects_missing_key():
    try:
        cue_io.format_cues_via_cloud({"segments": [{"i": 0, "text": "x"}]},
                                     provider="claude", api_key="")
        assert False, "expected ImportRejected"
    except dio.ImportRejected:
        pass
    print("  PASS test_format_cues_via_cloud_rejects_missing_key")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_validate_cues_happy_path,
    test_validate_cues_accepts_bare_sound_design,
    test_validate_cues_drops_out_of_range_and_inverted,
    test_validate_cues_coalesces_overlapping_scenes,
    test_validate_cues_clamps_gain_and_duration,
    test_validate_cues_keeps_unknown_tag,
    test_validate_cues_default_sfx_anchor,
    test_validate_cues_bad_shape_raises,
    test_build_cue_export_shape,
    test_prompt_lists_vocabulary,
    test_import_cues_writes_rows,
    test_import_cues_review_lock_requires_force,
    test_format_cues_via_cloud_parses_provider_output,
    test_format_cues_via_cloud_rejects_missing_key,
]

if __name__ == "__main__":
    print("Running cue_io tests...\n")
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
