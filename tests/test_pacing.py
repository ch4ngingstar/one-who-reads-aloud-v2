import io
from pathlib import Path
import json
import shutil
import subprocess
import wave

import numpy as np
import pytest

from audio_assembler import AudioAssembler
from pacing import NATURAL_PAUSES, mark_paragraphs, pause_ms
from speech_audio import tighten_edges
from state_manager import StateManager

RATE = 24000


def take(lead_ms=0, voiced_ms=500, tail_ms=0, gap_ms=0, amplitude=8000):
    """Silence, tone, optional inner silence, tone, silence — like a recorded line."""
    tone = (np.sin(2 * np.pi * 220 * np.arange(int(RATE * voiced_ms / 1000)) / RATE) * amplitude)
    parts = [np.zeros(int(RATE * lead_ms / 1000)), tone]
    if gap_ms:
        parts += [np.zeros(int(RATE * gap_ms / 1000)), tone]
    parts.append(np.zeros(int(RATE * tail_ms / 1000)))
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", ""))
        wav.writeframes(np.concatenate(parts).astype("<i2").tobytes())
    return out.getvalue()


def duration_ms(audio):
    with wave.open(io.BytesIO(audio)) as wav:
        return wav.getnframes() / wav.getframerate() * 1000


def test_edges_are_trimmed_to_the_same_padding_whatever_the_engine_left():
    omni_like = tighten_edges(take(lead_ms=660, tail_ms=290))
    fish_like = tighten_edges(take(lead_ms=0, tail_ms=160))
    # 500 ms of speech + 30 ms lead + 60 ms tail (the lead pad only where there was silence).
    assert abs(duration_ms(omni_like) - 590) <= 10
    assert abs(duration_ms(fish_like) - 560) <= 10


def test_pauses_inside_a_take_are_kept():
    trimmed = tighten_edges(take(lead_ms=400, gap_ms=700, tail_ms=400))
    assert abs(duration_ms(trimmed) - (500 + 700 + 500 + 30 + 60)) <= 10


def test_silent_or_unusual_takes_are_left_alone():
    silent = take(voiced_ms=0, lead_ms=250)
    assert tighten_edges(silent) == silent
    stereo = io.BytesIO()
    with wave.open(stereo, "wb") as wav:
        wav.setparams((2, 2, RATE, 0, "NONE", ""))
        wav.writeframes(b"\x00\x00\x00\x00" * 100)
    assert tighten_edges(stereo.getvalue()) == stereo.getvalue()


def test_a_quiet_whisper_keeps_its_onset():
    # The threshold follows the take's own peak, so a whisper (~-44 dBFS) is not mistaken
    # for silence; only audio under the -55 dBFS noise floor is.
    whisper = tighten_edges(take(lead_ms=300, amplitude=300, tail_ms=300))
    assert abs(duration_ms(whisper) - 590) <= 10


def test_paragraphs_are_found_in_the_chapter_source():
    chunks = ["The writing was on the wall.\n\nSunny frowned. “Who’s there?”",
              "Nobody answered.\n\n‘Strange…’ he thought."]
    lines = [{"text": "The writing was on the wall."}, {"text": "Sunny frowned."},
             {"text": "Who's there?"}, {"text": "Nobody answered."}, {"text": "Strange..."},
             {"text": "he thought."}]
    mark_paragraphs(lines, chunks)
    assert [line["paragraph_start"] for line in lines] == [True, True, False, True, True, False]


def test_an_edited_line_counts_as_a_new_paragraph_without_losing_the_place():
    lines = [{"text": "First paragraph."}, {"text": "Completely rewritten by the editor."},
             {"text": "Second sentence of it."}]
    mark_paragraphs(lines, ["First paragraph. Second sentence of it."])
    assert [line["paragraph_start"] for line in lines] == [True, True, False]


def test_natural_pause_table():
    narrator = {"speaker": "Narrator", "kind": "prose", "text": "He looked up."}
    quote = {"speaker": "Sunny", "kind": "dialogue", "text": "Who's there?", "paragraph_start": False}
    assert pause_ms(narrator, quote, 200, 380, NATURAL_PAUSES) == NATURAL_PAUSES["turn"]
    assert pause_ms(narrator, {**quote, "paragraph_start": True}, 200, 380, NATURAL_PAUSES) == \
        NATURAL_PAUSES["paragraph_turn"]
    assert pause_ms(narrator, {**narrator, "paragraph_start": True}, 200, 380, NATURAL_PAUSES) == \
        NATURAL_PAUSES["paragraph"]
    tail = {"speaker": "Narrator", "kind": "prose", "text": "he said."}
    assert pause_ms({**quote, "text": "Wait,"}, tail, 200, 380, NATURAL_PAUSES) == NATURAL_PAUSES["attached"]
    # Without a pause table the legacy fixed gaps are unchanged.
    assert pause_ms(narrator, quote, 200, 380) == 380


def seeded_chapter(tmp_path, takes):
    sm = StateManager(tmp_path / "pipeline.db")
    project = sm.seed_project({"source_epub": "shadow-slave-vol9.epub", "total_chapters": 1, "chapters": [{
        "chapter_index": 0, "title": "Chapter 1994  Call to Arms",
        "chunks": [{"chunk_index": 0, "word_count": 9,
                    "text": "The writing was on the wall.\n\nSunny frowned. “Who’s there?”"}]}]})
    chapter = sm.get_all_chapters(project)[0]["id"]
    sm.save_diarized_lines(chapter, [
        {"line_index": 0, "speaker": "Narrator", "kind": "prose", "text": "The writing was on the wall.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Narrator", "kind": "prose", "text": "Sunny frowned.", "emotion": "neutral"},
        {"line_index": 2, "speaker": "Sunny", "kind": "dialogue", "text": "Who's there?", "emotion": "neutral"}])
    for line, audio in zip(sm.get_pending_tts_lines(chapter), takes):
        path = tmp_path / f"line_{line['line_index']}.wav"
        path.write_bytes(audio)
        sm.mark_line_tts_done(line["id"], str(path))
    return sm, chapter


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
def test_natural_assembly_is_engine_independent_and_tagged(tmp_path):
    takes = [take(lead_ms=600, tail_ms=250), take(lead_ms=0, tail_ms=150), take(lead_ms=200, tail_ms=300)]
    sm, chapter = seeded_chapter(tmp_path, takes)
    master = AudioAssembler(sm, tmp_path / "out", cfg={"output_format": "wav"}).assemble_chapter(chapter)
    # 3 × (500 ms speech + edge pads) + a paragraph gap (520) + an in-paragraph turn (380).
    expected = (500 + 30 + 60) + 520 + (500 + 60) + 380 + (500 + 30 + 60)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", master],
        check=True, capture_output=True, text=True).stdout)["format"]
    assert abs(float(probe["duration"]) * 1000 - expected) <= 25
    tags = {k.lower(): v for k, v in probe.get("tags", {}).items()}
    assert tags.get("title") == "Chapter 1994: Call to Arms"
    assert tags.get("artist") == "Guiltythree"
    # The recorded takes themselves are never modified.
    assert [(tmp_path / f"line_{i}.wav").read_bytes() for i in range(3)] == takes


def test_legacy_pacing_still_concatenates_raw_takes(tmp_path):
    sm, chapter = seeded_chapter(tmp_path, [take(lead_ms=600), take(), take()])
    asm = AudioAssembler(sm, tmp_path / "out", cfg={"pacing": "legacy", "tag_metadata": False})
    asm._check_ffmpeg = lambda: None
    listed = []
    asm._run_ffmpeg = lambda list_path, out: (listed.append(list_path.read_text(encoding="utf-8")),
                                              out.write_bytes(b"x" * 5000))
    asm.assemble_chapter(chapter)
    assert "line_0.wav" in listed[0] and "edge_" not in listed[0]


def test_files_are_named_by_book_and_real_chapter(tmp_path):
    sm, chapter = seeded_chapter(tmp_path, [take(), take(), take()])
    asm = AudioAssembler(sm, tmp_path / "out", cfg={"output_format": "wav", "tag_metadata": False})
    master = Path(asm.assemble_chapter(chapter))
    assert master.parent.name == "Shadow Slave, Volume 9"
    assert master.name == "1994 - Call to Arms.wav"
    legacy = AudioAssembler(sm, tmp_path / "old", cfg={"output_format": "wav", "tag_metadata": False,
                                                       "book_layout": False})
    assert Path(legacy.assemble_chapter(chapter)).name == f"ch_{chapter:04d}.wav"
