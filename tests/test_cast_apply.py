import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cast import apply_votes, decode  # noqa: E402
from state_manager import StateManager  # noqa: E402

OMNI = "models/omnivoice-runtime/checkpoints"
FISH = "models/audio-cpp/Fish-Audio-S2-Pro-GGUF"


def setup(tmp_path):
    sm = StateManager(tmp_path / "pipeline.db")
    old = tmp_path / "jet.wav"
    old.write_bytes(b"RIFF-old")
    sm.set_voice("Jet", str(old))
    sm.set_voice("Kai", str(old))
    cand = tmp_path / "design" / "cand_2.wav"
    cand.parent.mkdir()
    cand.write_bytes(b"RIFF-new")
    cand.with_suffix(".json").write_text(json.dumps({"reference_script": "Relax. Let me do the talking."}))
    profile = tmp_path / "full-cast.json"
    profile.write_text(json.dumps({"narrator": OMNI, "characters": FISH, "actors": {"Jet": OMNI}}))
    key = {"pack": "abc123def", "characters": {
        "Jet": {"cand_2:A": {"voice": "cand_2", "engine": "Fish S2 Pro", "reference": str(cand)},
                "current:A": {"voice": "current", "engine": "OmniVoice", "reference": str(old)}},
        "Kai": {"cand_1:A": {"voice": "cand_1", "engine": "Fish S2 Pro", "reference": str(cand)}}}}
    return sm, old, profile, key


def test_a_picked_design_is_registered_and_routed_without_touching_the_old_clip(tmp_path):
    sm, old, profile, key = setup(tmp_path)
    votes = {"pack": "abc123def", "picks": {"Jet": {"pick": "cand_2:A", "notes": "cold, good"}}}
    applied = apply_votes(votes, key, sm, profile, tmp_path / "editions", tmp_path / "decisions.json")
    new_path = Path(sm.get_voice_map()["Jet"]["path"])
    assert new_path.parent == tmp_path / "editions" and new_path.read_bytes() == b"RIFF-new"
    assert new_path.with_suffix(".txt").read_text(encoding="utf-8").strip() == "Relax. Let me do the talking."
    assert old.read_bytes() == b"RIFF-old"
    # Fish is the default character engine, so Jet's OmniVoice override is removed.
    assert "Jet" not in json.loads(profile.read_text())["actors"]
    log = json.loads((tmp_path / "decisions.json").read_text())
    assert log[0]["character"] == "Jet" and log[0]["previous"] == str(old) and applied[0]["notes"] == "cold, good"


def test_keeping_the_current_voice_only_sets_the_engine(tmp_path):
    sm, old, profile, key = setup(tmp_path)
    apply_votes({"pack": "abc123def", "picks": {"Jet": {"pick": "current:A"}}}, key, sm, profile,
                tmp_path / "editions", tmp_path / "decisions.json")
    assert sm.get_voice_map()["Jet"]["path"] == str(old)
    assert json.loads(profile.read_text())["actors"]["Jet"] == OMNI


def test_protected_voices_are_never_replaced(tmp_path):
    sm, old, profile, key = setup(tmp_path)
    with pytest.raises(SystemExit, match="protected"):
        apply_votes({"pack": "abc123def", "picks": {"Kai": {"pick": "cand_1:A"}}}, key, sm, profile,
                    tmp_path / "editions", tmp_path / "decisions.json")
    assert sm.get_voice_map()["Kai"]["path"] == str(old)


def test_votes_for_another_pack_are_rejected_and_none_is_skipped(tmp_path):
    _, _, _, key = setup(tmp_path)
    with pytest.raises(SystemExit, match="pack"):
        decode({"pack": "other", "picks": {}}, key)
    assert decode({"pack": "abc123def", "picks": {"Jet": {"pick": "none"}}}, key) == {}


@pytest.mark.parametrize("brief,expected", [
    ("A boy about seven years old. Bright, clear, sweet child's voice.", "child"),
    ("A small boy about 6; soft, gentle voice.", "child"),
    ("A woman in her late twenties, a deadly veteran soldier.", "female"),
    ("A man around thirty-five; rough, hoarse, weary voice.", "male"),
    ("An inhuman monster speaking in a deep, guttural voice.", None),
])
def test_briefs_say_what_pitch_to_expect(brief, expected):
    from voice_screening import expected_profile
    assert expected_profile(brief) == expected


def test_label_audit_trusts_explicit_attributions_and_ignores_handoffs():
    from label_audit import find_conflicts
    def line(i, speaker, kind, text):
        return {"id": i, "chapter_id": 1, "line_index": i, "speaker": speaker, "kind": kind, "text": text}
    lines = [line(0, "Narrator", "prose", "Nephis frowned."),
             line(1, "Sunny", "dialogue", "What about the duel?"),
             line(2, "Narrator", "prose", "Sunny looked at Nephis."),
             line(3, "Nephis", "dialogue", "We have not decided."),
             line(4, "Sunny", "dialogue", "Fine,"),
             line(5, "Narrator", "prose", "Nephis said quietly."),
             line(6, "Nephis", "dialogue", "Locked line.")]
    lines[6]["speaker_locked"] = 1
    found = {(c["line_index"], c["evidence"], c["strength"]) for c in find_conflicts(lines)}
    assert found == {(1, "Nephis", "beat"), (4, "Nephis", "explicit")}
