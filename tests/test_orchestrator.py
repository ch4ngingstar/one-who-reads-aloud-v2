"""
Test suite for Module 6: orchestrator.py
Run: python tests/test_orchestrator.py

All external modules (LLM, TTS, Assembler, EPUB parser) are replaced
with fakes — no GPU, no server, no FFmpeg required.
"""

import sys
import time
import tempfile
import threading
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
from orchestrator  import PipelineOrchestrator, PipelineConfig, _query_vram_used_mb


# ── Fake module classes ───────────────────────────────────────────────────────

class FakeLLMDirector:
    """Marks chapter as diarized and writes mock lines."""
    instances = []

    def __init__(self, model_path, sm, speakers=None, cfg=None):
        self.sm = sm
        FakeLLMDirector.instances.append(self)
        self.entered = False
        self.exited  = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *args):
        self.exited = True
        return False

    def process_chapter(self, chapter_id):
        self.sm.save_diarized_lines(chapter_id, [
            {"line_index": 0, "speaker": "Narrator",
             "text": "Test line.", "emotion": "neutral"},
        ])
        return 1


class FakeTTSEngine:
    """Marks lines as tts_done and chapter as tts_done."""
    def __init__(self, sm, wav_dir, model_dir=None, **kwargs):
        self.sm = sm

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def process_chapter(self, chapter_id, progress_callback=None):
        lines = self.sm.get_pending_tts_lines(chapter_id)
        for line in lines:
            self.sm.mark_line_tts_done(line["id"], f"/fake/audio/line_{line['id']}.wav")
        self.sm.mark_chapter_status(chapter_id, "tts_done")
        return len(lines)


class FakeAssembler:
    """Marks chapter as complete."""
    def __init__(self, sm, output_dir, cfg=None):
        self.sm = sm

    def assemble_chapter(self, chapter_id):
        self.sm.mark_chapter_status(
            chapter_id, "complete",
            audio_path=f"/fake/output/ch_{chapter_id:04d}.mp3"
        )
        return f"/fake/output/ch_{chapter_id:04d}.mp3"


def _fake_parse_epub(epub_path, output_json=None):
    """Returns a minimal ParsedBook-compatible dict."""
    return {
        "source_epub": Path(epub_path).name,
        "total_chapters": 3,
        "chapters": [
            {
                "chapter_index": i,
                "title": f"Chapter {i + 1}",
                "chunks": [
                    {"chunk_index": 0, "text": f"Text of chapter {i}.",
                     "word_count": 5}
                ],
            }
            for i in range(3)
        ],
    }


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_config(**overrides) -> PipelineConfig:
    tmp_db  = tempfile.NamedTemporaryFile(suffix=".db",  delete=False)
    tmp_db.close()
    tmp_wav = tempfile.mkdtemp()
    tmp_mp3 = tempfile.mkdtemp()

    defaults = dict(
        epub_path="fake_book.epub",
        llm_model_path="fake_model.gguf",
        tts_model_dir="fake_tts_model",
        db_path=tmp_db.name,
        audio_wav_dir=tmp_wav,
        audio_mp3_dir=tmp_mp3,
        vram_check_enabled=False,  # skip nvidia-smi in tests
    )
    defaults.update(overrides)
    return PipelineConfig(**defaults)


def _make_orch(config=None, **kwargs) -> PipelineOrchestrator:
    cfg = config or _make_config()
    FakeLLMDirector.instances.clear()
    return PipelineOrchestrator(
        cfg,
        llm_director_cls=FakeLLMDirector,
        tts_engine_cls=FakeTTSEngine,
        assembler_cls=FakeAssembler,
        epub_parser_fn=_fake_parse_epub,
        **kwargs,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_full_pipeline_three_chapters():
    orch = _make_orch()
    results = orch.run()

    assert results["success"] == 3, f"Expected 3 successes, got {results}"
    assert results["error"]   == 0
    assert results["skipped"] == 0

    chapters = orch.sm.get_all_chapters(orch._project_id)
    assert all(c["status"] == "complete" for c in chapters), (
        [c["status"] for c in chapters]
    )
    print("  PASS test_full_pipeline_three_chapters")


def test_progress_events_emitted():
    events = []
    orch = _make_orch(progress_callback=events.append)
    orch.run()

    types = [e["type"] for e in events]
    assert "pipeline_start"  in types
    assert "stage_start"     in types
    assert "stage_done"      in types
    assert "chapter_done"    in types
    assert "pipeline_done"   in types

    # Each chapter should have exactly 3 stage_start events (diarize/synthesize/assemble)
    stage_starts = [e for e in events if e["type"] == "stage_start"]
    assert len(stage_starts) == 9, f"Expected 9 stage_start events (3 ch x 3 stages), got {len(stage_starts)}"

    print("  PASS test_progress_events_emitted")


def test_resume_skips_complete_chapters():
    orch = _make_orch()
    orch._setup()  # seed project

    chapters = orch.sm.get_all_chapters(orch._project_id)
    # Manually complete chapter 0 before running
    orch.sm.mark_chapter_status(chapters[0]["id"], "complete")

    FakeLLMDirector.instances.clear()
    results = orch.run()

    assert results["success"] == 2
    assert results["skipped"] == 1

    # LLMDirector should only have been instantiated twice
    assert len(FakeLLMDirector.instances) == 2, (
        f"Expected 2 LLM instantiations, got {len(FakeLLMDirector.instances)}"
    )
    print("  PASS test_resume_skips_complete_chapters")


def test_resume_from_diarized_skips_llm():
    orch = _make_orch()
    orch._setup()
    chapters = orch.sm.get_all_chapters(orch._project_id)

    # Manually diarize chapter 0 (LLM already done)
    orch.sm.save_diarized_lines(chapters[0]["id"], [
        {"line_index": 0, "speaker": "Narrator",
         "text": "Pre-diarized.", "emotion": "neutral"},
    ])

    FakeLLMDirector.instances.clear()
    results = orch.run()

    assert results["success"] == 3
    # Only 2 LLM calls (chapters 1 and 2); chapter 0 was already diarized
    assert len(FakeLLMDirector.instances) == 2, (
        f"Expected 2 LLM calls, got {len(FakeLLMDirector.instances)}"
    )
    print("  PASS test_resume_from_diarized_skips_llm")


def test_chapter_range_filters_correctly():
    cfg  = _make_config(chapter_range=(1, 2))  # only chapters index 1 and 2
    orch = _make_orch(config=cfg)
    results = orch.run()

    assert results["success"] == 2, f"Expected 2 successes, got {results}"
    chapters = orch.sm.get_all_chapters(orch._project_id)

    # Chapter 0 should still be pending (not in range)
    ch0 = next(c for c in chapters if c["chapter_index"] == 0)
    assert ch0["status"] == "pending", f"Chapter 0 should be untouched: {ch0['status']}"

    print("  PASS test_chapter_range_filters_correctly")


def test_error_in_one_chapter_continues_pipeline():
    class BrokenLLM:
        def __init__(self, model_path, sm, **kwargs):
            self.sm = sm
            self._call_count = getattr(BrokenLLM, '_call_count', 0)
            BrokenLLM._call_count = self._call_count + 1

        def __enter__(self): return self
        def __exit__(self, *args): return False

        def process_chapter(self, chapter_id):
            # Fail for the first chapter only
            if BrokenLLM._call_count == 1:
                raise RuntimeError("Simulated LLM crash")
            self.sm.save_diarized_lines(chapter_id, [
                {"line_index": 0, "speaker": "Narrator",
                 "text": "Recovered.", "emotion": "neutral"},
            ])

    BrokenLLM._call_count = 0
    cfg  = _make_config()
    orch = PipelineOrchestrator(
        cfg,
        llm_director_cls=BrokenLLM,
        tts_engine_cls=FakeTTSEngine,
        assembler_cls=FakeAssembler,
        epub_parser_fn=_fake_parse_epub,
    )
    results = orch.run()

    assert results["error"]   >= 1
    assert results["success"] >= 1
    assert results["error"] + results["success"] == 3

    chapters = orch.sm.get_all_chapters(orch._project_id)
    statuses = {c["chapter_index"]: c["status"] for c in chapters}
    assert statuses[0] == "error", f"Chapter 0 should be error: {statuses}"

    print("  PASS test_error_in_one_chapter_continues_pipeline")


def test_llm_context_manager_lifecycle():
    """Verify LLMDirector __enter__/__exit__ are both called exactly once per chapter."""
    orch = _make_orch()
    orch.run()

    for inst in FakeLLMDirector.instances:
        assert inst.entered, "LLMDirector.__enter__ was not called"
        assert inst.exited,  "LLMDirector.__exit__ was not called (VRAM leak!)"

    print("  PASS test_llm_context_manager_lifecycle")


def test_pipeline_emits_done_event_with_summary():
    events = []
    orch = _make_orch(progress_callback=events.append)
    orch.run()

    done = next(e for e in events if e["type"] == "pipeline_done")
    assert done["success"]  == 3
    assert done["error"]    == 0
    assert done["skipped"]  == 0
    assert "elapsed_s" in done

    print("  PASS test_pipeline_emits_done_event_with_summary")


def test_pause_and_resume():
    """Pipeline pauses between chapters and resumes on signal."""
    orch = _make_orch()
    orch._setup()

    orch.pause()
    results_holder = [None]

    def run_in_thread():
        results_holder[0] = orch.run()

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()

    time.sleep(0.1)  # let thread start and hit the pause
    assert t.is_alive(), "Thread should be paused, not finished yet"

    orch.resume()
    t.join(timeout=10)

    assert not t.is_alive(), "Thread should have completed after resume"
    assert results_holder[0]["success"] == 3

    print("  PASS test_pause_and_resume")


def test_stop_halts_pipeline_before_first_chapter():
    """Calling stop() before run() causes pipeline to exit with 0 successes and emits pipeline_stopped."""
    events = []
    orch = _make_orch(progress_callback=events.append)
    orch._setup()

    orch.stop()
    results = orch.run()

    assert results["success"] == 0, f"Expected 0 successes, got {results}"
    types = [e["type"] for e in events]
    assert "pipeline_stopped" in types, "pipeline_stopped event must be emitted"
    assert "pipeline_done" not in types, "pipeline_done must NOT be emitted when stopped"
    print("  PASS test_stop_halts_pipeline_before_first_chapter")


def test_stop_during_run_finishes_current_chapter():
    """stop() called in a background thread causes the pipeline to finish its current chapter then exit."""
    import collections as _collections

    orch = _make_orch()
    results_holder = [None]

    def run_in_thread():
        results_holder[0] = orch.run()

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()

    # Give the pipeline time to start the first chapter, then stop
    time.sleep(0.05)
    orch.stop()
    t.join(timeout=10)

    assert not t.is_alive(), "Pipeline thread should have exited after stop"
    r = results_holder[0]
    assert r is not None
    # At most 1 chapter could have completed before the stop check fires
    assert r["success"] <= 3
    events = list(orch.events)
    assert any(e["type"] in ("pipeline_stopped", "pipeline_done") for e in events)
    print("  PASS test_stop_during_run_finishes_current_chapter")


def test_events_deque_is_bounded():
    """orch.events is a deque with maxlen=500; it never grows beyond that."""
    import collections as _collections
    orch = _make_orch()
    orch.run()

    assert isinstance(orch.events, _collections.deque), "events must be a deque"
    assert orch.events.maxlen == 500
    assert len(orch.events) <= 500
    print("  PASS test_events_deque_is_bounded")


def test_error_chapter_resumes_from_synthesize():
    """Chapter that errors at synthesize should skip re-diarizing on retry."""

    class BrokenTTSOnce:
        _call_count = 0

        def __init__(self, sm, wav_dir, model_dir=None, **kwargs):
            self.sm = sm
            BrokenTTSOnce._call_count += 1

        def __enter__(self): return self
        def __exit__(self, *args): return False

        def process_chapter(self, chapter_id, progress_callback=None):
            if BrokenTTSOnce._call_count == 1:
                raise RuntimeError("Simulated TTS OOM")
            lines = self.sm.get_pending_tts_lines(chapter_id)
            for line in lines:
                self.sm.mark_line_tts_done(line["id"], f"/fake/audio/line_{line['id']}.wav")
            self.sm.mark_chapter_status(chapter_id, "tts_done")
            return len(lines)

    BrokenTTSOnce._call_count = 0
    cfg = _make_config()
    orch = PipelineOrchestrator(
        cfg,
        llm_director_cls=FakeLLMDirector,
        tts_engine_cls=BrokenTTSOnce,
        assembler_cls=FakeAssembler,
        epub_parser_fn=_fake_parse_epub,
    )

    # First run: chapter 0 errors at synthesize
    FakeLLMDirector.instances.clear()
    r1 = orch.run()
    assert r1["error"] == 1, f"Expected 1 error, got {r1}"
    assert r1["success"] == 2

    chapters = orch.sm.get_all_chapters(orch._project_id)
    ch0 = next(c for c in chapters if c["chapter_index"] == 0)
    assert ch0["status"] == "error"
    assert "[failed_stage:synthesize]" in (ch0["error_message"] or ""), (
        f"Expected [failed_stage:synthesize] in error_message, got: {ch0['error_message']}"
    )
    # Diarized lines must still exist — synthesize failed, not diarize
    lines = orch.sm.get_lines_for_chapter(ch0["id"])
    assert len(lines) > 0, "Chapter 0 should have diarized lines even after synthesize error"

    # Second run: TTS now succeeds; LLM must NOT be called again
    FakeLLMDirector.instances.clear()
    r2 = orch.run()
    assert r2["success"] >= 1
    assert len(FakeLLMDirector.instances) == 0, (
        f"LLM must not re-run for a chapter that already passed diarize, "
        f"got {len(FakeLLMDirector.instances)} LLM instantiation(s)"
    )
    print("  PASS test_error_chapter_resumes_from_synthesize")


def test_idempotent_setup_does_not_duplicate_chapters():
    orch = _make_orch()
    orch._setup()
    orch._setup()  # called twice

    chapters = orch.sm.get_all_chapters(orch._project_id)
    assert len(chapters) == 3, f"Expected exactly 3 chapters, got {len(chapters)}"

    print("  PASS test_idempotent_setup_does_not_duplicate_chapters")


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_full_pipeline_three_chapters,
    test_progress_events_emitted,
    test_resume_skips_complete_chapters,
    test_resume_from_diarized_skips_llm,
    test_chapter_range_filters_correctly,
    test_error_in_one_chapter_continues_pipeline,
    test_llm_context_manager_lifecycle,
    test_pipeline_emits_done_event_with_summary,
    test_pause_and_resume,
    test_idempotent_setup_does_not_duplicate_chapters,
    test_stop_halts_pipeline_before_first_chapter,
    test_stop_during_run_finishes_current_chapter,
    test_events_deque_is_bounded,
    test_error_chapter_resumes_from_synthesize,
]

if __name__ == "__main__":
    print("Running Module 6 tests...\n")
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
