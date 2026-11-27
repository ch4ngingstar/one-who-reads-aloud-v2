import json
import shutil
import subprocess

import pytest

from book_export import BookExports, ExportError, build_metadata, export, ffmeta_escape
from state_manager import StateManager

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="needs ffmpeg")


def tone_mp3(path, seconds):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=220:duration={seconds}", "-ac", "1", str(path)], check=True)
    return path


def volume(tmp_path):
    sm = StateManager(tmp_path / "pipeline.db")
    project = sm.seed_project({"source_epub": "x.epub", "total_chapters": 4, "chapters": [
        {"chapter_index": 0, "title": "Shadow Slave", "chunks": []},
        {"chapter_index": 1, "title": "Chapter 1841  First", "chunks": []},
        {"chapter_index": 2, "title": "Chapter 1842: Second", "chunks": []},
        {"chapter_index": 3, "title": "Chapter 1843  Third", "chunks": []}]})
    chapters = sm.get_all_chapters(project)
    for chapter, seconds in zip(chapters[1:3], (2, 3)):
        audio = tone_mp3(tmp_path / f"ch_{chapter['id']}.mp3", seconds)
        sm.mark_chapter_status(chapter["id"], "complete", audio_path=str(audio))
    return project


def test_metadata_escapes_and_chains_chapters():
    text, total = build_metadata([{"title": "A=B; #1"}, {"title": "C"}], [1000, 2500], "Vol", "Auth")
    assert "title=A\\=B\\; \\#1" in text
    assert "START=1000\nEND=3500" in text and total == 3500
    assert ffmeta_escape("back\\slash") == "back\\\\slash"


@needs_ffmpeg
def test_finished_chapters_become_one_book_with_markers(tmp_path):
    project = volume(tmp_path)
    out = tmp_path / "book.m4b"
    result = export(tmp_path / "pipeline.db", project, out)
    assert result["chapters"] == 2 and result["missing"] == 1  # chapter 1843 is unfinished
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json",
                                       str(out)], capture_output=True, text=True, check=True).stdout)
    titles = [c["tags"]["title"] for c in probe["chapters"]]
    assert titles == ["Chapter 1841: First", "Chapter 1842: Second"]
    assert abs(float(probe["chapters"][1]["start_time"]) - 2.0) < 0.15
    assert probe["format"]["tags"]["genre"] == "Audiobook"


@needs_ffmpeg
def test_strict_refuses_a_volume_with_gaps(tmp_path):
    project = volume(tmp_path)
    with pytest.raises(ExportError, match="strict"):
        export(tmp_path / "pipeline.db", project, tmp_path / "book.m4b", strict=True)
    assert not (tmp_path / "book.m4b").exists()


@needs_ffmpeg
def test_a_chapter_range_limits_the_book(tmp_path):
    project = volume(tmp_path)
    result = export(tmp_path / "pipeline.db", project, tmp_path / "one.m4b", first=1842, last=1842)
    assert result["chapters"] == 1 and result["missing"] == 0


def test_background_export_reports_progress_and_errors(tmp_path):
    import threading
    release = threading.Event()

    def slow_runner(db, project, out, log):
        release.wait(5)
        if project == 2:
            raise ExportError("No finished chapters to export yet")
        return {"chapters": 3, "missing": 0, "hours": 0.5, "file": str(out)}

    sm = StateManager(tmp_path / "pipeline.db")
    first = sm.seed_project({"source_epub": "vol9.epub", "total_chapters": 0, "chapters": []})
    second = sm.seed_project({"source_epub": "vol10.epub", "total_chapters": 0, "chapters": []})
    exports = BookExports(tmp_path / "books", runner=slow_runner)
    assert exports.status(first)["state"] == "idle"
    started = exports.start(tmp_path / "pipeline.db", first)
    assert started["state"] == "running"
    # A second request while running returns the same job instead of starting another.
    assert exports.start(tmp_path / "pipeline.db", first)["started"] == started["started"]
    exports.start(tmp_path / "pipeline.db", second)
    release.set()
    for _ in range(100):
        if exports.status(first)["state"] != "running" and exports.status(second)["state"] != "running":
            break
        threading.Event().wait(0.05)
    assert exports.status(first)["state"] == "done" and exports.status(first)["chapters"] == 3
    assert exports.status(second)["state"] == "error"
    assert "No finished chapters" in exports.status(second)["error"]
