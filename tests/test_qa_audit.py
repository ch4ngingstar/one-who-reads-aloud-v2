"""
Test suite for qa_audit.py (read-only correctness audit).
Run: python tests/test_qa_audit.py

Temp SQLite via StateManager. No GPU, no model. ffprobe is monkeypatched for
the duration check; all other checks are pure DB reads.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import qa_audit
from qa_audit import audit_project, AuditConfig
from state_manager import StateManager


# ── Fixtures ────────────────────────────────────────────────────────────────────

def _tmp_sm() -> StateManager:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed(sm: StateManager, n_chapters: int = 1) -> int:
    book = {
        "source_epub": "shadow_slave.epub",
        "total_chapters": n_chapters,
        "chapters": [
            {
                "chapter_index": i,
                "title": f"Chapter {i + 1}",
                "chunks": [{"chunk_index": 0, "text": "word " * 10, "word_count": 10}],
            }
            for i in range(n_chapters)
        ],
    }
    return sm.seed_project(book)


def _first_chapter_id(sm: StateManager, project_id: int) -> int:
    return sm.get_all_chapters(project_id)[0]["id"]


def _codes(report) -> set:
    return {f.code for f in report.findings}


def _by_code(report, code):
    return [f for f in report.findings if f.code == code]


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_unknown_project_raises():
    sm = _tmp_sm()
    try:
        audit_project(sm, 999)
        assert False, "expected ValueError for unknown project"
    except ValueError:
        pass


def test_clean_project_no_findings():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.set_voice("Sunny", "voices/sunny.wav")
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "Sunny", "text": "Hello there.", "emotion": "neutral"},
        {"line_index": 1, "speaker": "Sunny", "text": "How are you?", "emotion": "happy"},
    ])
    # Diarized chapter, every speaker mapped -> no pre-flight findings.
    report = audit_project(sm, pid)
    assert report.findings == [], f"expected clean, got {_codes(report)}"
    assert report.summary["total_findings"] == 0


def test_preflight_unmapped_hard():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    # No voices registered at all -> unmapped, no _default.
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "Nightmare Spawn", "text": "Grr.", "emotion": "angry"},
    ])
    report = audit_project(sm, pid)
    assert "preflight_unmapped_hard" in _codes(report)
    f = _by_code(report, "preflight_unmapped_hard")[0]
    assert f.severity == "high"
    assert "Nightmare Spawn" in f.detail["speakers"]


def test_preflight_unmapped_soft_with_default():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.set_voice("_default", "voices/default.wav")
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "Random NPC", "text": "Hi.", "emotion": "neutral"},
    ])
    report = audit_project(sm, pid)
    codes = _codes(report)
    assert "preflight_unmapped_soft" in codes
    assert "preflight_unmapped_hard" not in codes
    assert _by_code(report, "preflight_unmapped_soft")[0].severity == "medium"


def test_failed_unmapped_and_synth():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "one", "emotion": "neutral"},
        {"line_index": 1, "speaker": "B", "text": "two", "emotion": "neutral"},
        {"line_index": 2, "speaker": "C", "text": "three", "emotion": "neutral"},
    ])
    lines = sm.get_lines_for_chapter(cid)
    sm.mark_line_failed(lines[0]["id"], "No reference audio for speaker 'A'.")
    sm.mark_line_failed(lines[1]["id"], "CUDA out of memory")
    sm.mark_line_tts_done(lines[2]["id"], "data/audio/ch/line_0002.wav")
    sm.mark_chapter_status(cid, "tts_done")

    report = audit_project(sm, pid)
    codes = _codes(report)
    assert "failed_unmapped" in codes
    assert "failed_synth" in codes


def test_completion_shortfall():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.save_diarized_lines(cid, [
        {"line_index": i, "speaker": "A", "text": "x", "emotion": "neutral"}
        for i in range(10)
    ])
    lines = sm.get_lines_for_chapter(cid)
    for ln in lines[:8]:  # only 8/10 synthesised -> 80% < 98%
        sm.mark_line_tts_done(ln["id"], "p.wav")
    sm.mark_chapter_status(cid, "tts_done")

    report = audit_project(sm, pid)
    assert "completion_shortfall" in _codes(report)
    f = _by_code(report, "completion_shortfall")[0]
    assert f.detail["synthesized"] == 8 and f.detail["total"] == 10


def test_empty_text():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "real text", "emotion": "neutral"},
        {"line_index": 1, "speaker": "A", "text": "   ", "emotion": "neutral"},
    ])
    lines = sm.get_lines_for_chapter(cid)
    for ln in lines:
        sm.mark_line_tts_done(ln["id"], "p.wav")
    sm.mark_chapter_status(cid, "tts_done")

    report = audit_project(sm, pid)
    assert "empty_text" in _codes(report)
    assert _by_code(report, "empty_text")[0].detail["line_indexes"] == [1]


def test_speaker_collapse():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    # 25 lines, 25/25 = 100% Narrator -> collapse (min_lines=20, pct>=0.97).
    sm.save_diarized_lines(cid, [
        {"line_index": i, "speaker": "Narrator", "text": "x", "emotion": "neutral"}
        for i in range(25)
    ])
    lines = sm.get_lines_for_chapter(cid)
    for ln in lines:
        sm.mark_line_tts_done(ln["id"], "p.wav")
    sm.mark_chapter_status(cid, "tts_done")

    report = audit_project(sm, pid)
    assert "speaker_collapse" in _codes(report)
    assert _by_code(report, "speaker_collapse")[0].severity == "low"


def test_speaker_collapse_skipped_when_short():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    # 5 lines all Narrator: below collapse_min_lines -> NOT flagged.
    sm.save_diarized_lines(cid, [
        {"line_index": i, "speaker": "Narrator", "text": "x", "emotion": "neutral"}
        for i in range(5)
    ])
    lines = sm.get_lines_for_chapter(cid)
    for ln in lines:
        sm.mark_line_tts_done(ln["id"], "p.wav")
    sm.mark_chapter_status(cid, "tts_done")

    report = audit_project(sm, pid)
    assert "speaker_collapse" not in _codes(report)


def test_chapter_error():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.mark_chapter_status(cid, "error",
                           error_message="[failed_stage:diarize] boom")
    report = audit_project(sm, pid)
    assert "chapter_error" in _codes(report)


def test_mp3_missing():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "x", "emotion": "neutral"}])
    sm.mark_line_tts_done(sm.get_lines_for_chapter(cid)[0]["id"], "p.wav")
    sm.mark_chapter_status(cid, "complete")  # complete but no audio path
    report = audit_project(sm, pid)
    assert "mp3_missing" in _codes(report)


def test_mp3_tiny(monkeypatched_ffprobe_absent=None):
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    tiny = Path(tempfile.gettempdir()) / "qa_tiny.mp3"
    tiny.write_bytes(b"\x00" * 100)  # < 4096
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "x", "emotion": "neutral"}])
    sm.mark_line_tts_done(sm.get_lines_for_chapter(cid)[0]["id"], "p.wav")
    sm.mark_chapter_status(cid, "complete", audio_path=str(tiny))
    report = audit_project(sm, pid)
    assert "mp3_tiny" in _codes(report)
    tiny.unlink()


def test_duration_anomaly(monkey_ok=True):
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    big = Path(tempfile.gettempdir()) / "qa_big.mp3"
    big.write_bytes(b"\x00" * 10000)  # > mp3_min_bytes
    # 100 words -> expected ~40s at 150wpm. Force ffprobe to report 5s -> ratio ~0.12.
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "word " * 100, "emotion": "neutral"}])
    sm.mark_line_tts_done(sm.get_lines_for_chapter(cid)[0]["id"], "p.wav")
    sm.mark_chapter_status(cid, "complete", audio_path=str(big))

    orig_avail, orig_probe = qa_audit._ffprobe_available, qa_audit._probe_duration_s
    qa_audit._ffprobe_available = lambda: True
    qa_audit._probe_duration_s = lambda p: 5.0
    try:
        report = audit_project(sm, pid)
    finally:
        qa_audit._ffprobe_available, qa_audit._probe_duration_s = orig_avail, orig_probe
        big.unlink()
    assert "duration_anomaly" in _codes(report)


def test_duration_ok_when_in_band():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    big = Path(tempfile.gettempdir()) / "qa_ok.mp3"
    big.write_bytes(b"\x00" * 10000)
    sm.save_diarized_lines(cid, [
        {"line_index": 0, "speaker": "A", "text": "word " * 100, "emotion": "neutral"}])
    sm.mark_line_tts_done(sm.get_lines_for_chapter(cid)[0]["id"], "p.wav")
    sm.mark_chapter_status(cid, "complete", audio_path=str(big))

    orig_avail, orig_probe = qa_audit._ffprobe_available, qa_audit._probe_duration_s
    qa_audit._ffprobe_available = lambda: True
    qa_audit._probe_duration_s = lambda p: 40.0  # ~expected -> in band
    try:
        report = audit_project(sm, pid)
    finally:
        qa_audit._ffprobe_available, qa_audit._probe_duration_s = orig_avail, orig_probe
        big.unlink()
    assert "duration_anomaly" not in _codes(report)


def test_chapter_range_filters():
    sm = _tmp_sm()
    pid = _seed(sm, n_chapters=3)
    for ch in sm.get_all_chapters(pid):
        sm.mark_chapter_status(ch["id"], "error", error_message="boom")
    report = audit_project(sm, pid, chapter_range=(0, 0))
    assert report.summary["chapters_audited"] == 1
    assert all(f.chapter_index == 0 for f in report.findings)


def test_summary_counts_and_serialization():
    sm = _tmp_sm()
    pid = _seed(sm)
    cid = _first_chapter_id(sm, pid)
    sm.mark_chapter_status(cid, "error", error_message="boom")
    report = audit_project(sm, pid)
    assert report.summary["by_code"].get("chapter_error") == 1
    d = report.to_dict()
    assert d["findings"][0]["code"] == "chapter_error"
    assert "generated_at" in d


TESTS = [
    test_unknown_project_raises,
    test_clean_project_no_findings,
    test_preflight_unmapped_hard,
    test_preflight_unmapped_soft_with_default,
    test_failed_unmapped_and_synth,
    test_completion_shortfall,
    test_empty_text,
    test_speaker_collapse,
    test_speaker_collapse_skipped_when_short,
    test_chapter_error,
    test_mp3_missing,
    test_mp3_tiny,
    test_duration_anomaly,
    test_duration_ok_when_in_band,
    test_chapter_range_filters,
    test_summary_counts_and_serialization,
]

if __name__ == "__main__":
    print("Running qa_audit tests...\n")
    passed, failed = 0, 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f"  ok   {test.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
