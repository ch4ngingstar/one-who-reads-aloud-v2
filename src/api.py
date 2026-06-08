"""
Module 7: FastAPI Backend
===========================
Exposes the pipeline and state DB over HTTP.
The Next.js UI (Module 8) calls these endpoints.

Run:  uvicorn src.api:app --reload --port 8000

ENDPOINTS:
  GET  /api/health
  POST /api/project                  create project (parse EPUB + seed DB)
  GET  /api/project/{name}           project info + progress
  POST /api/pipeline/start           start orchestrator in background thread
  POST /api/pipeline/pause           pause between chapters
  POST /api/pipeline/resume          resume after pause
  GET  /api/pipeline/status          current status + last-event snapshot
  GET  /api/chapters/{project_id}    chapter list with per-chapter status
  GET  /api/voices                   all registered voices
  POST /api/voices                   upsert a voice mapping (local path)
  POST /api/voices/upload            upsert a voice (file upload)
  DELETE /api/voices/{speaker}       remove a voice
  GET  /api/audio/{chapter_id}       stream the finished MP3
  GET  /api/events                   SSE stream of real-time pipeline events

DATA FLOW into Module 8 (Next.js):
  All JSON responses match the state DB contracts from Module 2.
  SSE events match the PipelineOrchestrator event schema from Module 6.
"""

import asyncio
import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from state_manager import StateManager
from orchestrator  import PipelineOrchestrator, PipelineConfig
from epub_parser   import parse_epub


# ── Pydantic request/response models ─────────────────────────────────────────

class ProjectCreate(BaseModel):
    epub_path:       str
    llm_model_path:  str
    fish_speech_dir: str
    speakers:        list[str] = []
    db_path:         str = "data/pipeline.db"
    audio_wav_dir:   str = "data/audio"
    audio_mp3_dir:   str = "data/output"


class PipelineStart(BaseModel):
    project_name:       str
    llm_model_path:     str
    fish_speech_dir:    str
    speakers:           list[str] = []
    chapter_range:      Optional[list[int]] = None   # [start, end] inclusive
    output_format:      str   = "mp3"
    managed_tts_server: bool  = True
    vram_check_enabled: bool  = True


class VoiceSet(BaseModel):
    speaker:        str
    ref_audio_path: str
    ref_text:       str = ""   # transcript of the reference clip for better voice cloning


class VoiceRefText(BaseModel):
    ref_text: str


# ── Pipeline manager ──────────────────────────────────────────────────────────

class PipelineManager:
    """
    Manages the single running orchestrator instance.
    Bridges the sync orchestrator thread to async SSE subscribers.
    """

    def __init__(self) -> None:
        self.orchestrator: Optional[PipelineOrchestrator] = None
        self.thread:       Optional[threading.Thread]     = None
        self.status:       str  = "idle"   # idle|running|paused|complete|error
        self.last_results: Optional[dict] = None
        self._subscribers: list[asyncio.Queue] = []
        self._loop:        Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── Subscriber management for SSE ────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _on_progress(self, event: dict) -> None:
        """Called from the orchestrator's background thread."""
        if self._loop:
            for q in list(self._subscribers):
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(
        self,
        config: PipelineConfig,
        sm: StateManager,
        llm_director_cls=None,
        tts_engine_cls=None,
        assembler_cls=None,
        epub_parser_fn=None,
    ) -> None:
        if self.status == "running":
            raise ValueError("Pipeline is already running.")

        kwargs = {}
        if llm_director_cls: kwargs["llm_director_cls"] = llm_director_cls
        if tts_engine_cls:   kwargs["tts_engine_cls"]   = tts_engine_cls
        if assembler_cls:    kwargs["assembler_cls"]     = assembler_cls
        if epub_parser_fn:   kwargs["epub_parser_fn"]   = epub_parser_fn

        self.orchestrator = PipelineOrchestrator(
            config,
            progress_callback=self._on_progress,
            **kwargs,
        )
        self.status = "running"

        def _run() -> None:
            try:
                self.last_results = self.orchestrator.run()
                self.status = "complete"
            except Exception as exc:
                self.status = "error"
                self._on_progress({"type": "pipeline_error", "error": str(exc)})

        self.thread = threading.Thread(target=_run, name="pipeline", daemon=True)
        self.thread.start()

    def pause(self) -> None:
        if self.orchestrator and self.status == "running":
            self.orchestrator.pause()
            self.status = "paused"

    def resume(self) -> None:
        if self.orchestrator and self.status == "paused":
            self.orchestrator.resume()
            self.status = "running"

    def stop(self) -> None:
        if self.orchestrator and self.status in ("running", "paused"):
            self.orchestrator.stop()
            self.status = "stopped"

    def get_status(self) -> dict:
        events = self.orchestrator.events if self.orchestrator else []
        return {
            "status":       self.status,
            "last_results": self.last_results,
            "event_count":  len(events),
            "last_event":   events[-1] if events else None,
        }


# ── FastAPI app ───────────────────────────────────────────────────────────────

_SRC_DIR = Path(__file__).parent
_DATA_DIR = _SRC_DIR / "data"

@asynccontextmanager
async def lifespan(app: FastAPI):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.state.sm      = StateManager(str(_DATA_DIR / "pipeline.db"))
    app.state.manager = PipelineManager()
    app.state.manager.set_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Shadow Slave Audiobook Pipeline", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Dependency injection ──────────────────────────────────────────────────────

def get_sm() -> StateManager:
    return app.state.sm

def get_manager() -> PipelineManager:
    return app.state.manager


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Project ───────────────────────────────────────────────────────────────────

@app.post("/api/project", status_code=201)
async def create_project(
    req: ProjectCreate,
    sm: StateManager = Depends(get_sm),
):
    """Parse the EPUB and seed the database. Does not start the pipeline."""
    epub_path = Path(req.epub_path)
    if not epub_path.exists():
        raise HTTPException(status_code=400,
                            detail=f"EPUB not found: {req.epub_path}")

    parsed      = parse_epub(req.epub_path)
    project_id  = sm.seed_project(parsed)
    project     = sm.get_project(epub_path.stem)
    progress    = sm.get_progress(project_id)
    return {"project_id": project_id, "project": project, "progress": progress}


@app.get("/api/project/{name}")
async def get_project(
    name: str,
    sm: StateManager = Depends(get_sm),
):
    project = sm.get_project(name)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found.")
    progress = sm.get_progress(project["id"])
    return {"project": project, "progress": progress}


# ── Pipeline control ──────────────────────────────────────────────────────────

@app.post("/api/pipeline/start")
async def start_pipeline(
    req: PipelineStart,
    sm: StateManager   = Depends(get_sm),
    mgr: PipelineManager = Depends(get_manager),
):
    project = sm.get_project(req.project_name)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{req.project_name}' not found. Call POST /api/project first."
        )

    if req.chapter_range:
        if len(req.chapter_range) != 2:
            raise HTTPException(status_code=400,
                                detail="chapter_range must have exactly 2 elements: [start, end]")
        if req.chapter_range[0] < 0:
            raise HTTPException(status_code=400,
                                detail="chapter_range indices must be non-negative")
        if req.chapter_range[0] > req.chapter_range[1]:
            raise HTTPException(status_code=400,
                                detail="chapter_range[0] (start) must be <= chapter_range[1] (end)")

    ch_range = tuple(req.chapter_range) if req.chapter_range else None

    config = PipelineConfig(
        epub_path         = project["source_epub"],
        llm_model_path    = req.llm_model_path,
        fish_speech_dir   = req.fish_speech_dir,
        db_path           = "data/pipeline.db",
        audio_wav_dir     = "data/audio",
        audio_mp3_dir     = "data/output",
        speakers          = req.speakers,
        chapter_range     = ch_range,
        output_format     = req.output_format,
        managed_tts_server= req.managed_tts_server,
        vram_check_enabled= req.vram_check_enabled,
    )

    try:
        mgr.start(config, sm)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {"status": "started", "project": req.project_name}


@app.post("/api/pipeline/pause")
async def pause_pipeline(mgr: PipelineManager = Depends(get_manager)):
    mgr.pause()
    return {"status": mgr.status}


@app.post("/api/pipeline/resume")
async def resume_pipeline(mgr: PipelineManager = Depends(get_manager)):
    mgr.resume()
    return {"status": mgr.status}


@app.post("/api/pipeline/stop")
async def stop_pipeline(mgr: PipelineManager = Depends(get_manager)):
    mgr.stop()
    return {"status": mgr.status}


@app.get("/api/pipeline/status")
async def pipeline_status(mgr: PipelineManager = Depends(get_manager)):
    return mgr.get_status()


# ── Chapters ──────────────────────────────────────────────────────────────────

@app.get("/api/chapters/{project_id}")
async def list_chapters(
    project_id: int,
    sm: StateManager = Depends(get_sm),
):
    chapters = sm.get_all_chapters(project_id)
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found.")
    return {"chapters": chapters, "total": len(chapters)}


@app.delete("/api/chapters/{chapter_id}/audio")
async def delete_chapter_audio(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """Delete the assembled audio file for a chapter and clear its path from the DB."""
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    audio_path = row["output_audio_path"]
    if audio_path:
        p = Path(audio_path)
        if p.exists():
            p.unlink()
    sm.delete_chapter_audio(chapter_id)
    return {"deleted": chapter_id, "file": audio_path}


@app.post("/api/chapters/{chapter_id}/reset")
async def reset_chapter(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """Reset a chapter to pending so the pipeline will re-process it."""
    ok = sm.reset_chapter_to_pending(chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    return {"reset": chapter_id}


# ── Voices ────────────────────────────────────────────────────────────────────

@app.get("/api/voices")
async def list_voices(sm: StateManager = Depends(get_sm)):
    return {"voices": sm.get_all_voices()}


@app.post("/api/voices", status_code=201)
async def set_voice(req: VoiceSet, sm: StateManager = Depends(get_sm)):
    if not Path(req.ref_audio_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"Audio file not found: {req.ref_audio_path}"
        )
    sm.set_voice(req.speaker, req.ref_audio_path, req.ref_text)
    return {"speaker": req.speaker, "ref_audio_path": req.ref_audio_path,
            "ref_text": req.ref_text}


@app.post("/api/voices/upload", status_code=201)
async def upload_voice(
    speaker:  str   = Form(...),
    ref_text: str   = Form(""),
    file:     UploadFile = File(...),
    sm:       StateManager = Depends(get_sm),
):
    """Upload a WAV reference clip for a speaker, with optional transcript."""
    voices_dir = Path("data/voices")
    voices_dir.mkdir(parents=True, exist_ok=True)
    dest = voices_dir / f"{speaker.lower().replace(' ', '_')}.wav"
    content = await file.read()
    dest.write_bytes(content)
    sm.set_voice(speaker, str(dest), ref_text)
    return {"speaker": speaker, "ref_audio_path": str(dest), "ref_text": ref_text}


@app.patch("/api/voices/{speaker}/ref_text", status_code=200)
async def update_voice_ref_text(
    speaker: str,
    req:     VoiceRefText,
    sm:      StateManager = Depends(get_sm),
):
    """Update only the reference transcript for a voice (no file re-upload needed)."""
    found = sm.update_voice_ref_text(speaker, req.ref_text)
    if not found:
        raise HTTPException(status_code=404, detail=f"Voice '{speaker}' not found.")
    return {"speaker": speaker, "ref_text": req.ref_text}


@app.delete("/api/voices/{speaker}")
async def delete_voice(speaker: str, sm: StateManager = Depends(get_sm)):
    """Remove a voice mapping (does not delete the audio file)."""
    if not sm.delete_voice(speaker):
        raise HTTPException(status_code=404, detail=f"Voice '{speaker}' not found.")
    return {"deleted": speaker}


# ── Audio file serving ────────────────────────────────────────────────────────

@app.get("/api/audio/{chapter_id}")
async def serve_audio(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """Stream the finished chapter MP3."""
    # Prefer path stored in DB; fall back to default naming convention
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()

    db_path  = Path(row["output_audio_path"]) if row and row["output_audio_path"] else None
    mp3_path = Path("data/output") / f"ch_{chapter_id:04d}.mp3"
    wav_path = Path("data/output") / f"ch_{chapter_id:04d}.wav"

    for candidate in filter(None, [db_path, mp3_path, wav_path]):
        if candidate.exists():
            return FileResponse(
                str(candidate),
                media_type="audio/mpeg" if candidate.suffix == ".mp3" else "audio/wav",
                filename=candidate.name,
            )

    raise HTTPException(status_code=404,
                        detail=f"Audio for chapter {chapter_id} not yet generated.")


# ── SSE event stream ──────────────────────────────────────────────────────────

@app.get("/api/events")
async def event_stream(
    request: Request,
    mgr: PipelineManager = Depends(get_manager),
):
    """
    Server-Sent Events stream.
    Connect before starting the pipeline to receive all progress events.
    Each event is JSON: data: {...}\n\n
    A heartbeat comment ': ping' is sent every second when idle.
    """
    q = mgr.subscribe()

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("pipeline_done", "pipeline_error"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keep-alive
        finally:
            mgr.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        },
    )
