import sqlite3

import pytest

from casting import choose_voice
from cast_discovery import audition_quotes, speaker_estimates
from chapter_titles import (book_folder, chapter_filename, identify, is_heading_line,
                            strip_leaked_heading)
from performance_score import compile_score
from state_manager import StateManager


@pytest.mark.parametrize("title,number,name", [
    ("Chapter 1994  Call to Arms", 1994, "Call to Arms"),
    ("Chapter 1841: Evil Minds That Plot Destruction", 1841, "Evil Minds That Plot Destruction"),
    ("Chapter: 2232 Cold Front", 2232, "Cold Front"),
    ("Chapter '2362 Hunter and Prey", 2362, "Hunter and Prey"),
    ("2569 Demon Slayer", 2569, "Demon Slayer"),
    ("Chapter 252", 252, ""),
])
def test_every_heading_shape_gives_the_real_number_and_name(title, number, name):
    identity = identify(title)
    assert (identity.kind, identity.number, identity.name) == ("chapter", number, name)
    assert identity.display == (f"Chapter {number}: {name}" if name else f"Chapter {number}")


def test_contents_and_synopsis_pages_are_recognised():
    back = identify("Chapter 422", "Content from Chapter 1841: Evil Minds to Chapter 2260 Peace\n\neBook from 9Kafe")
    assert back.kind == "back" and back.number is None
    front = identify("Shadow Slave", "Growing up in poverty, Sunny never expected anything good from life.")
    assert (front.kind, front.display) == ("front", "Synopsis")


def test_file_and_folder_names_follow_the_book():
    assert chapter_filename(identify("Chapter 1994  Call to Arms"), "mp3") == "1994 - Call to Arms.mp3"
    assert chapter_filename(identify("Shadow Slave"), ".mp3") == "0000 - Synopsis.mp3"
    assert chapter_filename(identify('Chapter 2001: What? "Why"/How*'), "mp3") == "2001 - What Why How.mp3"
    assert book_folder("9kafe.com-shadow-slave-vol10-c2261-c2720") == "Shadow Slave, Volume 10"
    assert book_folder("demo_scene") == "demo_scene"


def test_a_leaked_heading_is_detected_but_prose_is_not():
    identity = identify("Chapter 2882 Angels in the Marble")
    assert strip_leaked_heading("2882 Angels in the Marble\n\nSome time later...", identity) == "Some time later..."
    assert is_heading_line("Chapter 2882: Angels in the Marble", identity)
    assert not is_heading_line("Angels and marble statues lined the hall of Chapter 2882.", identity)
    prose = "Some time later, Rain was in her new living quarters."
    assert strip_leaked_heading(prose, identity) == prose


def test_compile_score_silences_only_a_leading_heading_line(tmp_path):
    reference = tmp_path / "narrator.wav"
    reference.write_bytes(b"RIFF")
    lines = [{"id": 1, "line_index": 0, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
              "text": "2882 Angels in the Marble", "chapter_id": 9},
             {"id": 2, "line_index": 1, "speaker": "Narrator", "emotion": "neutral", "kind": "prose",
              "text": "2882 Angels in the Marble", "chapter_id": 9}]
    cues = compile_score(lines, {"Narrator": str(reference)}, {}, heading=identify("Chapter 2882 Angels in the Marble"))
    assert cues[0].spoken == "" and cues[1].spoken != ""


def test_npc_pools_rotate_per_chapter_and_principals_never_do():
    voices = {"The Bureaucrat": "a.wav", "The Bureaucrat #2": "b.wav", "The Bureaucrat #3": "c.wav", "Sunny": "s.wav"}
    assert [choose_voice("The Bureaucrat", "neutral", voices, variant=v).path for v in range(4)] == \
        ["a.wav", "b.wav", "c.wav", "a.wav"]
    assert choose_voice("The Bureaucrat", "neutral", voices).path == "a.wav"
    assert choose_voice("Npc_Female", "neutral", voices, variant=1).path == "b.wav"
    assert choose_voice("Sunny", "neutral", voices, variant=2).path == "s.wav"


def test_the_database_learns_real_chapter_identities(tmp_path):
    sm = StateManager(tmp_path / "pipeline.db")
    project = sm.seed_project({"source_epub": "vol9.epub", "total_chapters": 3, "chapters": [
        {"chapter_index": 0, "title": "Shadow Slave", "chunks": [{"chunk_index": 0, "text": "Synopsis.", "word_count": 1}]},
        {"chapter_index": 1, "title": "Chapter: 2232 Cold Front", "chunks": [{"chunk_index": 0, "text": "Prose.", "word_count": 1}]},
        {"chapter_index": 2, "title": "Chapter 3", "chunks": [{"chunk_index": 0, "text": "Content from Chapter 2232 to 2233", "word_count": 5}]}]})
    rows = [(c["chapter_number"], c["display_title"], c["kind"]) for c in sm.get_all_chapters(project)]
    assert rows == [(None, "Synopsis", "front"), (2232, "Chapter 2232: Cold Front", "chapter"),
                    (None, "Contents (not narrated)", "back")]


def test_quotes_are_credited_to_the_beat_before_them(tmp_path):
    sm = StateManager(tmp_path / "pipeline.db")
    text = ("Jet frowned.\n\n“Are you really just going to trade insults?”\n\n"
            "Sunny shrugged.\n\n“It worked last time, didn't it?”\n\n"
            "“It did not,” Jet said. “Not even once.”")
    sm.seed_project({"source_epub": "vol10.epub", "total_chapters": 1, "chapters": [
        {"chapter_index": 0, "title": "Chapter 2600 Talk", "chunks": [{"chunk_index": 0, "text": text, "word_count": 30}]}]})
    con = sqlite3.connect(tmp_path / "pipeline.db")
    stats = speaker_estimates(con, [1], name_min=0)
    assert stats["Jet"].est_dialogue == 2 and stats["Sunny"].est_dialogue == 1
    assert audition_quotes(stats, "Jet", count=1)[0]["text"].startswith("Are you really")
