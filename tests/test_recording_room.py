import io
import json
import wave

import numpy as np
import pytest

from audio_assembler import AudioAssembler
from recording_room import RecordingRoom
from state_manager import StateManager
from take_review import compare_reading


def tone(rate=22050):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", ""))
        samples = np.sin(2 * np.pi * 220 * np.arange(rate) / rate) * 5000
        wav.writeframes(samples.astype("<i2").tobytes())
    return output.getvalue()


class Provider:
    batch_size = 4

    def __init__(self, name):
        self.identity = self.name = name
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def render(self, requests):
        self.calls.append([t for _, t in requests])
        return [tone() for _ in requests]


class Reviewer:
    def check(self, audio, spoken):
        return {"review": False, "status": "checked", "score": 1}


def test_uncast_character_requires_a_deliberate_default(tmp_path):
    from performance_score import compile_score
    ref = tmp_path / "voice.wav"
    ref.write_bytes(tone())
    line = {"id": 7, "line_index": 0, "speaker": "Unknown",
            "emotion": "neutral", "text": "Who's there?", "kind": "dialogue"}
    with pytest.raises(ValueError, match="needs a voice for Unknown"):
        compile_score([line], {"Narrator": str(ref)}, {})
    cue, = compile_score([line], {"Narrator": str(ref), "_default": str(ref)}, {})
    assert cue.fallback


def test_recast_and_retake_invalidate_only_the_requested_audio(tmp_path):
    sm = StateManager(tmp_path / "test.db")
    ref = tmp_path / "actor.wav"
    ref.write_bytes(tone())
    sm.set_voice("Narrator", str(ref))
    sm.set_voice("Sunny", str(ref))
    project = sm.seed_project({"source_epub": "a.epub", "total_chapters": 1,
                               "chapters": [{"chapter_index": 0, "title": "A", "chunks": []}]})
    chapter = sm.get_all_chapters(project)[0]["id"]
    sm.save_diarized_lines(chapter, [
        {"line_index": i, "speaker": who, "text": t, "emotion": "neutral", "kind": kind}
        for i, (who, t, kind) in enumerate([
            ("Narrator", "Sunny woke up.", "prose"), ("Sunny", "Who is there?", "dialogue"),
            ("Narrator", "The room was quiet.", "prose")])])
    narr, actor = Provider("Narration"), Provider("Actors")
    root = tmp_path / "recordings"

    def record():
        with RecordingRoom(sm, root, "", provider=narr, reviewer=Reviewer()) as room:
            room.character_provider = actor
            room.process_chapter(chapter)
    record()
    assert narr.calls == [["Sunny woke up.", "The room was quiet."]]
    assert actor.calls == [["Who is there?"]]
    sm.set_pronunciation("Sunny", "Sonny")
    sm.queue_recording(chapter, 1)
    record()
    assert narr.calls[-1] == ["Sonny woke up."]
    assert actor.calls == [["Who is there?"], ["Who is there?"]]
    path = root / f"ch_{chapter:04d}" / "score.json"
    cues = json.loads(path.read_text("utf-8"))["cues"]
    assert [c["cached"] for c in cues] == [False, False, True]
    asm = AudioAssembler(sm, tmp_path / "output", cfg={"score_path": str(path), "output_format": "wav"})
    master = asm.assemble_chapter(chapter)
    from pathlib import Path
    sheet = json.loads(Path(master).with_suffix(".performance.json").read_text("utf-8"))
    assert [c["index"] for c in sheet["cues"]] == [0, 1, 2]
    # Natural pacing: each 1 s take starts a new paragraph with another voice (620 ms).
    assert [c["start_ms"] for c in sheet["cues"]] == [0, 1620, 3240]
    assert sheet["duration_ms"] == 4240
    original = Path(master).read_bytes()
    replacement = asm.assemble_chapter(chapter)
    # The new master keeps the chapter's real name; the one it replaced is kept in previous/.
    assert replacement == master
    kept = list((Path(master).parent / "previous").glob("*.wav"))
    assert len(kept) == 1 and kept[0].read_bytes() == original
    assert sm.get_chapter_by_id(chapter)["output_audio_path"] == replacement
    assert Path(replacement).with_suffix(".performance.json").is_file()


def test_readback_flags_a_missing_phrase_but_tolerates_a_name():
    assert compare_reading("Nephis closed the door behind her.", "Nefis closed the door behind her.")["review"] is False
    assert compare_reading("They opened the door and saw the mountains beyond it.", "They opened the door.")["review"]
    assert compare_reading("Thank you! No, stop... what?", "Thank you. Stop. What?")["review"]
    assert compare_reading("Run!", "")["review"]
    assert not compare_reading("I can't go.", "I cannot go.")["review"]


def test_open_quote_after_a_speech_cue_is_assigned_to_dialogue():
    from segmenter import segment_chunk
    lines = segment_chunk('Nephis paused, then added evenly:\n\n"Additionally, we can wait.\n\nThe fire went out.')
    assert [(l["kind"], l["text"]) for l in lines] == [
        ("prose", "Nephis paused, then added evenly:"), ("dialogue", "Additionally, we can wait."),
        ("prose", "The fire went out.")]
    assert segment_chunk('A damaged passage with a " mark.')[0]["kind"] == "prose"


def test_mixing_preserves_actor_dynamics_and_reduces_the_level_jump(tmp_path):
    from cast_mix import balance_cast, _samples
    def level(line):
        return 20 * np.log10(np.sqrt(np.mean(_samples(line)[1] ** 2)))
    lines, cues = [], []
    for i, (actor, scale) in enumerate([("Narrator", .24), ("Sunny", 1.3), ("Sunny", .65)]):
        path = tmp_path / f"{i}.wav"
        with wave.open(io.BytesIO(tone()), "rb") as src, wave.open(str(path), "wb") as dst:
            dst.setparams(src.getparams())
            pcm = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")
            dst.writeframes((pcm * scale).astype("<i2").tobytes())
        lines.append({"line_index": i, "audio_path": str(path)})
        cues.append({"index": i, "actor": actor, "emotion": "whispers" if i == 2 else "neutral"})
    output, _ = balance_cast(lines, cues, tmp_path)
    assert abs(level(output[0]) - level(output[1])) < 5
    assert abs(level(output[1]) - level(output[2]) - 6.02) < .1
