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
import re
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from state_manager import StateManager, CHAPTER_STATUSES
from orchestrator  import PipelineOrchestrator, PipelineConfig
from epub_parser   import parse_epub


# ── Pydantic request/response models ─────────────────────────────────────────

class ProjectCreate(BaseModel):
    epub_path:       str
    llm_model_path:  str
    tts_model_dir:   str = ""   # IndexTTS2 checkpoints dir
    fish_speech_dir: str = ""   # deprecated alias for tts_model_dir
    speakers:        list[str] = []
    db_path:         str = "data/pipeline.db"
    audio_wav_dir:   str = "data/audio"
    audio_mp3_dir:   str = "data/output"


class PipelineStart(BaseModel):
    project_name:       str
    llm_model_path:     str
    tts_model_dir:      str = ""   # IndexTTS2 checkpoints dir
    fish_speech_dir:    str = ""   # deprecated alias for tts_model_dir
    speakers:           list[str] = []
    chapter_range:      Optional[list[int]] = None   # [start, end] inclusive
    output_format:      str   = "mp3"
    vram_check_enabled: bool  = True

    @property
    def resolved_model_dir(self) -> str:
        """Prefer the new field; fall back to the deprecated fish_speech_dir."""
        return self.tts_model_dir or self.fish_speech_dir


class VoiceSet(BaseModel):
    speaker:        str
    ref_audio_path: str


class ChapterResetRange(BaseModel):
    project_id:     int
    status_filter:  Optional[list[str]] = None   # e.g. ["error", "tts_done"]; None = all
    chapter_range:  Optional[list[int]] = None   # [start_index, end_index] inclusive; None = all


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
        if self.thread and self.thread.is_alive():
            # stop() was called but the orchestrator is still finishing the
            # current chapter — starting now would double-load models in VRAM.
            raise ValueError(
                "Pipeline is still finishing the current chapter. "
                "Try again in a moment."
            )

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
                # A user-initiated stop must not be reported as "complete".
                self.status = "stopped" if self.orchestrator.stopped else "complete"
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

# All runtime paths are anchored absolutely so behaviour does not depend on the
# CWD uvicorn happens to be launched from (start.ps1 uses src/, manual runs use
# the repo root — both must hit the same DB and audio directories).
_SRC_DIR  = Path(__file__).resolve().parent
_ROOT_DIR = _SRC_DIR.parent
_DATA_DIR = _SRC_DIR / "data"              # DB + uploaded voices (legacy layout)
_VOICES_DIR    = _DATA_DIR / "voices"
_AUDIO_WAV_DIR = _ROOT_DIR / "data" / "audio"
_AUDIO_MP3_DIR = _ROOT_DIR / "data" / "output"


def _resolve_data_path(p: "str | Path") -> Path:
    """Resolve a possibly-relative DB-stored path. Legacy rows hold paths
    relative to the repo root; fall back to src/ for runs made with CWD=src."""
    path = Path(p)
    if path.is_absolute():
        return path
    root_candidate = _ROOT_DIR / path
    if root_candidate.exists():
        return root_candidate
    src_candidate = _SRC_DIR / path
    return src_candidate if src_candidate.exists() else root_candidate

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

    # Parsing is CPU-heavy (spaCy over hundreds of chapters) — keep it off the
    # event loop so /api/health and SSE heartbeats stay responsive.
    parsed      = await asyncio.to_thread(parse_epub, req.epub_path)
    project_id  = sm.seed_project(parsed)
    project     = sm.get_project(epub_path.stem)
    progress    = sm.get_progress(project_id)
    return {"project_id": project_id, "project": project, "progress": progress}


@app.get("/api/projects")
async def list_projects(sm: StateManager = Depends(get_sm)):
    """All projects with per-project progress, for the UI project picker."""
    return {"projects": sm.list_projects_with_progress()}


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

    model_dir = req.resolved_model_dir
    if not model_dir:
        raise HTTPException(
            status_code=400,
            detail="tts_model_dir is required (the IndexTTS2 checkpoints directory)."
        )

    config = PipelineConfig(
        epub_path         = project["source_epub"],
        llm_model_path    = req.llm_model_path,
        tts_model_dir     = model_dir,
        db_path           = str(_DATA_DIR / "pipeline.db"),
        audio_wav_dir     = str(_AUDIO_WAV_DIR),
        audio_mp3_dir     = str(_AUDIO_MP3_DIR),
        speakers          = req.speakers,
        chapter_range     = ch_range,
        output_format     = req.output_format,
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


@app.post("/api/chapters/reset-range", status_code=200)
async def reset_chapters_range(
    req: ChapterResetRange,
    sm: StateManager = Depends(get_sm),
):
    """Reset multiple chapters to pending.

    Filters by project_id, optional status_filter list, and optional
    chapter_range [start_index, end_index] inclusive. Returns reset chapter IDs.
    Chapters already at 'pending' are skipped.
    """
    if req.status_filter:
        invalid = set(req.status_filter) - CHAPTER_STATUSES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status values: {sorted(invalid)}. "
                       f"Valid: {sorted(CHAPTER_STATUSES)}"
            )

    if req.chapter_range:
        if len(req.chapter_range) != 2:
            raise HTTPException(status_code=400,
                                detail="chapter_range must have exactly 2 elements: [start, end]")
        if req.chapter_range[0] > req.chapter_range[1]:
            raise HTTPException(status_code=400,
                                detail="chapter_range[0] must be <= chapter_range[1]")

    all_chapters = sm.get_all_chapters(req.project_id)
    if not all_chapters:
        raise HTTPException(status_code=404,
                            detail=f"No chapters found for project_id={req.project_id}")

    candidates = all_chapters
    if req.status_filter:
        candidates = [c for c in candidates if c["status"] in req.status_filter]
    if req.chapter_range:
        s, e = req.chapter_range
        candidates = [c for c in candidates if s <= c["chapter_index"] <= e]

    to_reset = [c for c in candidates if c["status"] != "pending"]

    reset_ids: list[int] = []
    for ch in to_reset:
        ok = sm.reset_chapter_to_pending(ch["id"])
        if ok:
            if ch.get("output_audio_path"):
                p = _resolve_data_path(ch["output_audio_path"])
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            reset_ids.append(ch["id"])

    return {"reset": reset_ids, "count": len(reset_ids)}


@app.get("/api/chapters/{chapter_id}/lines")
async def list_chapter_lines(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """All diarized lines for a chapter (speaker, text, emotion, status, audio_path)."""
    lines = sm.get_lines_for_chapter(chapter_id)
    return {"lines": lines, "total": len(lines)}


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
        p = _resolve_data_path(audio_path)
        if p.exists():
            p.unlink()
    sm.delete_chapter_audio(chapter_id)
    return {"deleted": chapter_id, "file": audio_path}


@app.post("/api/chapters/{chapter_id}/reset")
async def reset_chapter(
    chapter_id: int,
    sm: StateManager = Depends(get_sm),
):
    """Reset a chapter to pending so the pipeline will re-process it.
    Also removes the assembled audio file so no orphan is left on disk."""
    with sm._conn() as conn:
        row = conn.execute(
            "SELECT output_audio_path FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chapter not found.")

    ok = sm.reset_chapter_to_pending(chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chapter not found.")

    if row["output_audio_path"]:
        p = _resolve_data_path(row["output_audio_path"])
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass  # file locked (e.g. playing) — DB is already reset
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
    sm.set_voice(req.speaker, req.ref_audio_path)
    return {"speaker": req.speaker, "ref_audio_path": req.ref_audio_path}


_ALLOWED_VOICE_EXTS = {".wav", ".mp3", ".flac", ".ogg"}


@app.post("/api/voices/upload", status_code=201)
async def upload_voice(
    speaker:  str   = Form(...),
    file:     UploadFile = File(...),
    sm:       StateManager = Depends(get_sm),
):
    """Upload a reference clip for a speaker."""
    speaker = speaker.strip()
    if not speaker:
        raise HTTPException(status_code=400, detail="Speaker name is required.")

    # Slug prevents path traversal / illegal filename characters.
    slug = re.sub(r"[^a-z0-9]+", "_", speaker.lower()).strip("_")
    if not slug:
        raise HTTPException(status_code=400,
                            detail=f"Speaker name '{speaker}' has no usable characters.")

    ext = Path(file.filename or "").suffix.lower() or ".wav"
    if ext not in _ALLOWED_VOICE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{ext}'. "
                   f"Allowed: {', '.join(sorted(_ALLOWED_VOICE_EXTS))}"
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    _VOICES_DIR.mkdir(parents=True, exist_ok=True)
    dest = _VOICES_DIR / f"{slug}{ext}"
    dest.write_bytes(content)
    sm.set_voice(speaker, str(dest))
    return {"speaker": speaker, "ref_audio_path": str(dest)}


@app.delete("/api/voices/{speaker}")
async def delete_voice(speaker: str, sm: StateManager = Depends(get_sm)):
    """Remove a voice mapping (does not delete the audio file)."""
    if not sm.delete_voice(speaker):
        raise HTTPException(status_code=404, detail=f"Voice '{speaker}' not found.")
    return {"deleted": speaker}


# ── Audio file serving ────────────────────────────────────────────────────────

_VOICE_MEDIA_TYPES = {
    ".wav":  "audio/wav",
    ".mp3":  "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg":  "audio/ogg",
}


@app.get("/api/voices/{speaker}/audio")
async def serve_voice_audio(speaker: str, sm: StateManager = Depends(get_sm)):
    """Stream a speaker's reference clip so the UI can preview voices."""
    voice = sm.get_voice_map().get(speaker)
    if voice is None:
        raise HTTPException(status_code=404, detail=f"Voice '{speaker}' not found.")

    path = _resolve_data_path(voice["path"])
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Reference clip for '{speaker}' is missing on disk: {voice['path']}",
        )

    media_type = _VOICE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media_type, filename=path.name)


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

    db_path = (_resolve_data_path(row["output_audio_path"])
               if row and row["output_audio_path"] else None)
    candidates = [db_path]
    # Default naming convention, checked in both historical output locations
    # (repo-root data/output for manual runs, src/data/output for CWD=src runs).
    for base in (_AUDIO_MP3_DIR, _DATA_DIR / "output"):
        candidates.append(base / f"ch_{chapter_id:04d}.mp3")
        candidates.append(base / f"ch_{chapter_id:04d}.wav")

    for candidate in filter(None, candidates):
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
                    if event.get("type") in ("pipeline_done", "pipeline_error",
                                             "pipeline_stopped"):
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
