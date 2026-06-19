"""
Test suite for Module 7: api.py
Run: python tests/test_api.py

Uses FastAPI TestClient + dependency overrides.
No real orchestrator, no GPU, no FFmpeg.
"""

import sys
import json
import tempfile
import wave
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi.testclient import TestClient
from api import app, get_sm, get_manager, PipelineManager
from state_manager import StateManager


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_project(sm: StateManager, n_chapters: int = 3) -> int:
    book = {
        "source_epub": "shadow_slave.epub",
        "total_chapters": n_chapters,
        "chapters": [
            {
                "chapter_index": i,
                "title": f"Chapter {i + 1}",
                "chunks": [{"chunk_index": 0, "text": "text", "word_count": 1}],
            }
            for i in range(n_chapters)
        ],
    }
    return sm.seed_project(book)


def _make_tiny_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 2205)
    return path


def _make_client(sm=None, mgr=None):
    """Create a TestClient with injected dependencies."""
    _sm  = sm  or _tmp_sm()
    _mgr = mgr or PipelineManager()

    app.dependency_overrides[get_sm]      = lambda: _sm
    app.dependency_overrides[get_manager] = lambda: _mgr

    return TestClient(app, raise_server_exceptions=True), _sm, _mgr


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health():
    client, _, _ = _make_client()
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    print("  PASS test_health")


def test_get_project_not_found():
    client, _, _ = _make_client()
    r = client.get("/api/project/nonexistent")
    assert r.status_code == 404
    print("  PASS test_get_project_not_found")


def test_get_project_found():
    sm = _tmp_sm()
    _seed_project(sm)
    client, _, _ = _make_client(sm=sm)

    r = client.get("/api/project/shadow_slave")
    assert r.status_code == 200
    data = r.json()
    assert data["project"]["name"] == "shadow_slave"
    assert data["progress"]["total"] == 3
    print("  PASS test_get_project_found")


def test_create_project_epub_not_found():
    client, _, _ = _make_client()
    r = client.post("/api/project", json={
        "epub_path":       "/does/not/exist.epub",
        "llm_model_path":  "model.gguf",
        "tts_model_dir":   "index-tts/checkpoints",
    })
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()
    print("  PASS test_create_project_epub_not_found")


def test_list_chapters():
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=5)
    client, _, _ = _make_client(sm=sm)

    r = client.get(f"/api/chapters/{pid}")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["chapters"]) == 5
    assert data["chapters"][0]["status"] == "pending"
    print("  PASS test_list_chapters")


def test_list_chapters_not_found():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)
    r = client.get("/api/chapters/9999")
    assert r.status_code == 404
    print("  PASS test_list_chapters_not_found")


def test_qa_audit_endpoint():
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=2)
    # Force one chapter into error so the audit has something to report.
    cid = sm.get_all_chapters(pid)[0]["id"]
    sm.mark_chapter_status(cid, "error", error_message="boom")
    client, _, _ = _make_client(sm=sm)

    r = client.get(f"/api/qa/audit?project_id={pid}")
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["chapters_audited"] == 2
    assert any(f["code"] == "chapter_error" for f in data["findings"])
    print("  PASS test_qa_audit_endpoint")


def test_qa_audit_unknown_project():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)
    r = client.get("/api/qa/audit?project_id=9999")
    assert r.status_code == 404
    print("  PASS test_qa_audit_unknown_project")


def test_qa_audit_bad_range():
    sm = _tmp_sm()
    pid = _seed_project(sm, n_chapters=2)
    client, _, _ = _make_client(sm=sm)
    r = client.get(f"/api/qa/audit?project_id={pid}&start=5")  # end missing
    assert r.status_code == 400
    print("  PASS test_qa_audit_bad_range")


def test_get_voices_empty():
    client, _, _ = _make_client()
    r = client.get("/api/voices")
    assert r.status_code == 200
    assert r.json()["voices"] == []
    print("  PASS test_get_voices_empty")


def test_set_voice_bad_path():
    client, _, _ = _make_client()
    r = client.post("/api/voices", json={
        "speaker":        "Sunny",
        "ref_audio_path": "/does/not/exist.wav",
    })
    assert r.status_code == 400
    print("  PASS test_set_voice_bad_path")


def test_set_and_get_voice():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = _make_tiny_wav(Path(f.name))

    r = client.post("/api/voices", json={
        "speaker":        "Sunny",
        "ref_audio_path": str(wav_path),
    })
    assert r.status_code == 201

    r = client.get("/api/voices")
    voices = r.json()["voices"]
    assert any(v["speaker"] == "Sunny" for v in voices)
    print("  PASS test_set_and_get_voice")


def test_upload_voice():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = _make_tiny_wav(Path(tmp) / "test.wav")

        with open(wav_path, "rb") as f:
            r = client.post(
                "/api/voices/upload",
                data={"speaker": "Nephis"},
                files={"file": ("nephis.wav", f, "audio/wav")},
            )

    assert r.status_code == 201
    data = r.json()
    assert data["speaker"] == "Nephis"
    assert "nephis" in data["ref_audio_path"].lower()
    print("  PASS test_upload_voice")


def test_delete_voice():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = _make_tiny_wav(Path(f.name))

    client.post("/api/voices", json={"speaker": "Cassie",
                                      "ref_audio_path": str(wav_path)})
    r = client.delete("/api/voices/Cassie")
    assert r.status_code == 200
    assert r.json()["deleted"] == "Cassie"

    voices = client.get("/api/voices").json()["voices"]
    assert not any(v["speaker"] == "Cassie" for v in voices)
    print("  PASS test_delete_voice")


def test_delete_voice_not_found():
    client, _, _ = _make_client()
    r = client.delete("/api/voices/UnknownSpeaker")
    assert r.status_code == 404
    print("  PASS test_delete_voice_not_found")


def test_voice_audio_serves_clip():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = _make_tiny_wav(Path(f.name))

    sm.set_voice("Sunny", str(wav_path))
    r = client.get("/api/voices/Sunny/audio")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert len(r.content) > 0
    print("  PASS test_voice_audio_serves_clip")


def test_voice_audio_not_found():
    client, _, _ = _make_client()
    r = client.get("/api/voices/UnknownSpeaker/audio")
    assert r.status_code == 404
    print("  PASS test_voice_audio_not_found")


def test_voice_audio_missing_file():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    # Register a voice whose clip has since vanished from disk. set_voice does
    # not validate existence, so this models a stale DB row.
    sm.set_voice("Ghost", r"C:\does\not\exist\ghost.wav")
    r = client.get("/api/voices/Ghost/audio")
    assert r.status_code == 404
    print("  PASS test_voice_audio_missing_file")


def test_pipeline_status_idle():
    mgr = PipelineManager()
    client, _, _ = _make_client(mgr=mgr)

    r = client.get("/api/pipeline/status")
    assert r.status_code == 200
    assert r.json()["status"] == "idle"
    print("  PASS test_pipeline_status_idle")


def test_pipeline_start_project_not_found():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    r = client.post("/api/pipeline/start", json={
        "project_name":    "nonexistent",
        "llm_model_path":  "model.gguf",
        "tts_model_dir":   "index-tts/checkpoints",
    })
    assert r.status_code == 404
    print("  PASS test_pipeline_start_project_not_found")


def test_pipeline_start_already_running():
    sm  = _tmp_sm()
    mgr = PipelineManager()
    mgr.status = "running"   # simulate already running
    client, _, _ = _make_client(sm=sm, mgr=mgr)

    _seed_project(sm)

    r = client.post("/api/pipeline/start", json={
        "project_name":    "shadow_slave",
        "llm_model_path":  "model.gguf",
        "tts_model_dir":   "index-tts/checkpoints",
    })
    assert r.status_code == 409
    print("  PASS test_pipeline_start_already_running")


def test_pause_and_resume_endpoints():
    mgr = PipelineManager()
    mgr.status = "running"

    # Give it a dummy orchestrator with pause/resume
    class FakeOrch:
        def pause(self):  mgr.status = "paused"
        def resume(self): mgr.status = "running"

    mgr.orchestrator = FakeOrch()
    client, _, _ = _make_client(mgr=mgr)

    r = client.post("/api/pipeline/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    r = client.post("/api/pipeline/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    print("  PASS test_pause_and_resume_endpoints")


def test_audio_not_found():
    sm = _tmp_sm()
    pid = _seed_project(sm)
    chapters = sm.get_all_chapters(pid)
    client, _, _ = _make_client(sm=sm)

    r = client.get(f"/api/audio/{chapters[0]['id']}")
    assert r.status_code == 404
    print("  PASS test_audio_not_found")


def test_audio_serves_file():
    sm = _tmp_sm()
    client, _, _ = _make_client(sm=sm)

    with tempfile.TemporaryDirectory() as out_dir:
        # Create a fake MP3
        mp3 = Path(out_dir) / "ch_0001.mp3"
        mp3.write_bytes(b"ID3FAKEMP3DATA")

        # Register a chapter with that audio path in DB
        pid = _seed_project(sm, 1)
        ch_id = sm.get_all_chapters(pid)[0]["id"]
        sm.mark_chapter_status(ch_id, "complete", audio_path=str(mp3))

        r = client.get(f"/api/audio/{ch_id}")
        assert r.status_code == 200
        assert r.content == b"ID3FAKEMP3DATA"

    print("  PASS test_audio_serves_file")


def test_sse_receives_event():
    """
    SSE endpoint delivers events and closes the stream on pipeline_done.
    Uses a mock queue that returns an event immediately (no real orchestrator).
    """
    import asyncio

    class ImmediateQueue:
        """Mock asyncio.Queue that returns one event instantly, then blocks."""
        def __init__(self, event):
            self._event = event
            self._done  = False

        async def get(self):
            if not self._done:
                self._done = True
                return self._event
            await asyncio.sleep(9999)   # never reached after stream closes

    done_event = {
        "type": "pipeline_done", "success": 3,
        "error": 0, "skipped": 0, "elapsed_s": 1.2,
    }
    mgr = PipelineManager()
    mgr.subscribe   = lambda: ImmediateQueue(done_event)
    mgr.unsubscribe = lambda q: None

    client, _, _ = _make_client(mgr=mgr)

    with client.stream("GET", "/api/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        received = []
        for line in r.iter_lines():
            if line.startswith("data:"):
                received.append(json.loads(line[5:].strip()))

    assert len(received) == 1
    assert received[0]["type"]    == "pipeline_done"
    assert received[0]["success"] == 3
    print("  PASS test_sse_receives_event")


# ── Cleanup ───────────────────────────────────────────────────────────────────

def _cleanup():
    app.dependency_overrides.clear()


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = [
    test_health,
    test_get_project_not_found,
    test_get_project_found,
    test_create_project_epub_not_found,
    test_list_chapters,
    test_list_chapters_not_found,
    test_qa_audit_endpoint,
    test_qa_audit_unknown_project,
    test_qa_audit_bad_range,
    test_get_voices_empty,
    test_set_voice_bad_path,
    test_set_and_get_voice,
    test_upload_voice,
    test_delete_voice,
    test_delete_voice_not_found,
    test_voice_audio_serves_clip,
    test_voice_audio_not_found,
    test_voice_audio_missing_file,
    test_pipeline_status_idle,
    test_pipeline_start_project_not_found,
    test_pipeline_start_already_running,
    test_pause_and_resume_endpoints,
    test_audio_not_found,
    test_audio_serves_file,
    test_sse_receives_event,
]

if __name__ == "__main__":
    print("Running Module 7 tests...\n")
    passed, failed = 0, 0
    for test in TESTS:
        _cleanup()
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    _cleanup()
    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
