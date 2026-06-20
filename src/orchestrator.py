"""
Module 6: Pipeline Orchestrator
==================================
Sequences Modules 1-5 chapter-by-chapter with resume support,
per-stage error isolation, and a progress callback for the FastAPI SSE stream.

VRAM LIFECYCLE ENFORCED HERE (STAGE-BATCHED):
  Chapters are processed in moderate sub-batches (cfg.batch_size). For EACH
  sub-batch the expensive model loads are paid ONCE, not once per chapter:
    0. Baseline snapshot     [ VRAM held by desktop apps before the LLM loads ]
    1. LLMDirector context  [ loads ~8.5GB ] → diarize EVERY chapter → [ purge ]
    2. VRAM barrier check   [ waits until usage returns to ~baseline before TTS ]
    3. TTSEngine context     [ IndexTTS2 ~8GB ] → synthesize EVERY chapter → [ unload ]
    4. AudioAssembler.assemble_chapter()  for every chapter [ CPU only, 0 VRAM ]

  This collapses the per-chapter load/unload/barrier tax (paid N times in the
  old chapter-at-a-time loop) to once per sub-batch. Per-chunk LLM calls are
  stateless, so diarization output is identical to the unbatched path. Batches
  stay small so a power cut never costs more than one batch of progress —
  every chapter still commits its status to SQLite as it finishes each stage.

  The barrier is delta-based: browsers/compositor VRAM is in the baseline and
  cancels out, so only memory the *pipeline* added is waited on.

RESUME LOGIC:
  pending   → run all three stages
  diarized  → skip LLM, run TTS + assemble
  tts_done  → skip LLM + TTS, run assemble only
  complete  → skip entirely
  error     → retry from beginning

PROGRESS EVENTS (emitted to callback and collected in self.events):
  { "type": "pipeline_start",  "project": str, "total": int,   "ts": float }
  { "type": "chapter_start",   "chapter_id": int, "title": str,  "stage": str }
  { "type": "stage_start",     "chapter_id": int, "stage": str,  "ts": float }
  { "type": "stage_done",      "chapter_id": int, "stage": str,  "elapsed_s": float }
  { "type": "chapter_done",    "chapter_id": int, "audio_path": str }
  { "type": "chapter_error",   "chapter_id": int, "stage": str,  "error": str }
  { "type": "chapter_skip",    "chapter_id": int, "reason": str }
  { "type": "vram_warning",    "used_mb": int,    "threshold_mb": int,
                                "baseline_mb": int }
  { "type": "pipeline_done",   "success": int,    "error": int,  "skipped": int,
                                "elapsed_s": float }
"""

import collections
import datetime
import re
import shutil
import subprocess
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from epub_parser    import parse_epub
from state_manager  import StateManager
from llm_director   import LLMDirector, DEFAULT_SPEAKERS
from tts_engine     import TTSEngine
from audio_assembler import AudioAssembler


# ── Stage routing (what to run given current chapter status) ──────────────────
_ALL_STAGES = ["diarize", "synthesize", "assemble"]

_STAGES_FOR_STATUS = {
    "pending":   _ALL_STAGES,
    "diarized":  _ALL_STAGES[1:],
    "tts_done":  _ALL_STAGES[2:],
    "assembled": [],
    "complete":  [],
    # "error" is handled dynamically — see PipelineOrchestrator._stages_for_chapter()
}

# The pipeline may leave this much VRAM above the pre-LLM baseline before the
# barrier warns. CUDA allocator caches and driver overhead make 0 unrealistic.
_VRAM_DELTA_ALLOWANCE_MB = 500

# tts_progress events carry the live line for the UI's Inspector stage; cap
# the text so a single long paragraph can't bloat the SSE stream.
_LIVE_TEXT_MAX_CHARS = 200


def _truncate_live_text(text) -> str:
    text = str(text or "")
    if len(text) <= _LIVE_TEXT_MAX_CHARS:
        return text
    return text[: _LIVE_TEXT_MAX_CHARS - 1] + "…"


# Absolute fallback when no baseline could be captured (nvidia-smi failed at
# snapshot time but works at barrier time — rare).
_VRAM_FALLBACK_THRESHOLD_MB = 1000


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    # Required
    epub_path:        str
    llm_model_path:   str
    tts_model_dir:    str   # IndexTTS2 checkpoints directory

    # Paths (sensible defaults)
    db_path:          str = "data/pipeline.db"
    audio_wav_dir:    str = "data/audio"
    audio_mp3_dir:    str = "data/output"

    # LLM
    speakers:         list = field(default_factory=lambda: list(DEFAULT_SPEAKERS))
    llm_n_gpu_layers: int  = -1

    # Assembly
    output_format:        str   = "mp3"
    min_lines_threshold:  float = 0.5

    # Behaviour
    vram_check_enabled:   bool = True
    vram_wait_timeout_s:  int  = 180   # seconds to poll for VRAM to drop before warning
    chapter_range:        "tuple[int,int] | None" = None  # (start_idx, end_idx) inclusive
    log_path:             str  = "data/pipeline.log"   # set "" to disable file logging
    cleanup_wavs:         bool = True   # delete per-line WAVs after successful assembly
    # Chapters per stage-batch: one LLM + one TTS load amortised across this many
    # chapters. Measured swap tax is ~47s/chapter (40s of it the IndexTTS2 load;
    # LLM load is 7s, the VRAM barrier is instant). Amortised: bs=8 → ~6s/chapter,
    # capturing ~90% of the saving vs bs=25 while getting audio out far sooner and
    # losing almost nothing to a power cut (status commits to SQLite per chapter).
    batch_size:           int  = 8


# ── Per-chapter batch state ─────────────────────────────────────────────────

class _ChapterPlan:
    """Mutable per-chapter state threaded through the three batched phases.

    `elapsed` accumulates only this chapter's own stage time (not wall-clock),
    so processing_seconds stays meaningful even though a chapter's diarize and
    assemble are now separated by other chapters' work within the batch.
    """
    __slots__ = ("chapter", "stages", "errored", "started", "elapsed")

    def __init__(self, chapter: dict, stages: list):
        self.chapter = chapter
        self.stages  = stages
        self.errored = False
        self.started = False
        self.elapsed = 0.0


# ── Orchestrator ──────────────────────────────────────────────────────────────

class PipelineOrchestrator:
    """
    Runs the full audiobook pipeline end-to-end with resume support.

    Dependency injection:
      Pass *_cls / *_fn kwargs to substitute mock modules during testing.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: "Callable[[dict], None] | None" = None,
        # Injectable for tests
        llm_director_cls=LLMDirector,
        tts_engine_cls=TTSEngine,
        assembler_cls=AudioAssembler,
        epub_parser_fn=parse_epub,
    ):
        self.cfg            = config
        self.sm             = StateManager(config.db_path)
        self.on_progress    = progress_callback or (lambda e: None)
        self._llm_cls       = llm_director_cls
        self._tts_cls       = tts_engine_cls
        self._assembler_cls = assembler_cls
        self._parse_epub    = epub_parser_fn

        self._project_id: Optional[int] = None
        self._pause_event = threading.Event()
        self._pause_event.set()   # set = unpaused
        self._stop_event  = threading.Event()
        self._stop_event.set()    # set = running (not stopped)
        self.events: collections.deque = collections.deque(maxlen=500)
        self._current_stage: str = "unknown"
        self._vram_baseline_mb: int = -1   # set per chapter, before the LLM loads

        self._log_lock = threading.Lock()
        self._log_file = None
        if config.log_path:
            log_p = Path(config.log_path)
            log_p.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_p, "a", encoding="utf-8", buffering=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Execute the full pipeline with STAGE-BATCHED scheduling.

        Chapters are grouped into sub-batches of cfg.batch_size. Within each
        sub-batch the LLM is loaded once to diarize every chapter, unloaded, the
        VRAM barrier is crossed once, then IndexTTS2 is loaded once to synthesize
        every chapter, and assembly runs on CPU. This pays the load/unload/barrier
        tax once per batch instead of once per chapter, while small batches keep a
        power cut from costing more than one batch of progress.

        Returns a summary dict:
          { "success": int, "error": int, "skipped": int, "elapsed_s": float }
        """
        t0 = time.time()
        if self._log_file:
            with self._log_lock:
                run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log_file.write(f"\n{'='*60}\n[{run_ts}] RUN START\n{'='*60}\n")

        try:
            # Step 1: Parse EPUB + seed DB
            self._setup()

            chapters = self._chapters_to_process()
            self._emit("pipeline_start",
                       project=Path(self.cfg.epub_path).stem,
                       total=len(chapters))

            results = {"success": 0, "error": 0, "skipped": 0}

            # Build the work plan; chapters needing no stages are skipped up front
            # (in chapter order) so the batches below contain only real work.
            plan: "list[_ChapterPlan]" = []
            for chapter in chapters:
                stages = self._stages_for_chapter(chapter)
                if not stages:
                    self._emit("chapter_skip",
                               chapter_id=chapter["id"],
                               reason=f"status={chapter['status']}")
                    results["skipped"] += 1
                    continue
                plan.append(_ChapterPlan(chapter, stages))

            # Process in moderate sub-batches: one model load/unload pair covers
            # the whole batch, but progress lost to a power cut is bounded by it.
            batch_size = max(1, self.cfg.batch_size)
            for start in range(0, len(plan), batch_size):
                self._pause_event.wait()           # blocks while paused
                if not self._stop_event.is_set():
                    break                          # stop() was called
                self._run_batch(plan[start:start + batch_size], results)

            elapsed = round(time.time() - t0, 1)
            if self._stop_event.is_set():
                self._emit("pipeline_done", elapsed_s=elapsed, **results)
            else:
                self._emit("pipeline_stopped", elapsed_s=elapsed, **results)
            return results
        finally:
            if self._log_file:
                with self._log_lock:
                    self._log_file.close()
                self._log_file = None

    def pause(self)  -> None: self._pause_event.clear()
    def resume(self) -> None: self._pause_event.set()
    def stop(self)   -> None:
        self._stop_event.clear()
        self._pause_event.set()  # unblock if paused so the stop check is reached

    @property
    def stopped(self) -> bool:
        """True once stop() has been requested (cleared = stopped)."""
        return not self._stop_event.is_set()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        """Parse EPUB and seed the DB (idempotent)."""
        project_name = Path(self.cfg.epub_path).stem
        existing     = self.sm.get_project(project_name)

        if existing:
            self._project_id = existing["id"]
            print(f"[orch] Resuming project '{project_name}' "
                  f"(id={self._project_id})")
            return

        print(f"[orch] New project -- parsing EPUB: {self.cfg.epub_path}")
        parsed = self._parse_epub(
            self.cfg.epub_path,
            output_json=str(Path(self.cfg.db_path).parent / "parsed_book.json"),
        )
        self._project_id = self.sm.seed_project(parsed)

    def _chapters_to_process(self) -> list:
        chapters = self.sm.get_all_chapters(self._project_id)
        r = self.cfg.chapter_range
        if r:
            start, end = r
            chapters = [c for c in chapters
                        if start <= c["chapter_index"] <= end]
        return chapters

    def _stages_for_chapter(self, chapter: dict) -> list:
        """Return stages to run based on status; error chapters resume from the failed stage."""
        status = chapter["status"]
        if status != "error":
            return list(_STAGES_FOR_STATUS.get(status, []))
        msg = chapter.get("error_message") or ""
        m = re.search(r"\[failed_stage:(\w+)\]", msg)
        if m:
            failed = m.group(1)
            try:
                return list(_ALL_STAGES[_ALL_STAGES.index(failed):])
            except ValueError:
                pass
        return list(_ALL_STAGES)

    # ── Batch execution ───────────────────────────────────────────────────────

    def _run_batch(self, batch: "list[_ChapterPlan]", results: dict) -> None:
        """
        Process one sub-batch through all three stages, loading each model at
        most once. Error isolation is per chapter: a failure marks that chapter
        'error' and drops it from later stages; the rest of the batch proceeds.
        A stop() request halts the batch cleanly between chapters.
        """
        # ── Phase 1: diarize the whole batch under ONE LLM load ──────────────
        diarize = [p for p in batch if "diarize" in p.stages]
        if diarize and self._stop_event.is_set():
            # Snapshot desktop VRAM once so the post-LLM barrier waits on the
            # pipeline's delta, not memory held by the browser/compositor.
            if self.cfg.vram_check_enabled:
                self._vram_baseline_mb = _query_vram_used_mb()
                if self._vram_baseline_mb >= 0:
                    print(f"[orch] VRAM baseline before LLM: {self._vram_baseline_mb} MB.")
            try:
                llm_cfg = {"n_gpu_layers": self.cfg.llm_n_gpu_layers}
                load_t0 = time.time()
                with self._llm_cls(
                    self.cfg.llm_model_path,
                    self.sm,
                    speakers=self.cfg.speakers,
                    cfg=llm_cfg,
                ) as director:
                    # Cold-load cost is paid ONCE here and amortised over the
                    # whole batch — logged so the per-chapter swap tax is visible.
                    self._emit("model_load", model="llm",
                               chapters=len(diarize),
                               elapsed_s=round(time.time() - load_t0, 1))
                    for p in diarize:
                        self._pause_event.wait()
                        if not self._stop_event.is_set():
                            break
                        self._ensure_started(p)
                        try:
                            p.elapsed += self._stage_diarize(director, p.chapter["id"])
                        except Exception as exc:
                            self._fail_chapter(p, "diarize", exc, results)
            except Exception as exc:
                # The model load itself failed — every chapter in this phase is
                # blocked. Mark them all so the batch doesn't silently stall.
                for p in diarize:
                    if not p.errored:
                        self._fail_chapter(p, "diarize", exc, results)
            # LLM unloaded on context exit — wait for VRAM before TTS loads.
            barrier_t0 = time.time()
            self._vram_barrier()
            self._emit("vram_barrier",
                       elapsed_s=round(time.time() - barrier_t0, 1))

        # ── Phase 2: synthesize the whole batch under ONE TTS load ───────────
        synth = [p for p in batch if "synthesize" in p.stages and not p.errored]
        if synth and self._stop_event.is_set():
            try:
                load_t0 = time.time()
                with self._tts_cls(
                    self.sm,
                    self.cfg.audio_wav_dir,
                    model_dir=self.cfg.tts_model_dir,
                ) as engine:
                    self._emit("model_load", model="tts",
                               chapters=len(synth),
                               elapsed_s=round(time.time() - load_t0, 1))
                    for p in synth:
                        self._pause_event.wait()
                        if not self._stop_event.is_set():
                            break
                        self._ensure_started(p)
                        try:
                            p.elapsed += self._stage_synthesize(engine, p.chapter["id"])
                        except Exception as exc:
                            self._fail_chapter(p, "synthesize", exc, results)
            except Exception as exc:
                for p in synth:
                    if not p.errored:
                        self._fail_chapter(p, "synthesize", exc, results)

        # ── Phase 3: assemble on CPU (no model resident in VRAM) ─────────────
        assemble = [p for p in batch if "assemble" in p.stages and not p.errored]
        for p in assemble:
            self._pause_event.wait()
            if not self._stop_event.is_set():
                break
            self._ensure_started(p)
            try:
                p.elapsed += self._stage_assemble(p.chapter["id"])
                self._complete_chapter(p, results)
            except Exception as exc:
                self._fail_chapter(p, "assemble", exc, results)

    # ── Per-chapter lifecycle helpers ─────────────────────────────────────────

    def _ensure_started(self, p: "_ChapterPlan") -> None:
        """Emit chapter_start exactly once, the first phase a chapter does work."""
        if p.started:
            return
        p.started = True
        ch = p.chapter
        self._emit("chapter_start",
                   chapter_id=ch["id"],
                   chapter_index=ch["chapter_index"],
                   title=ch["title"],
                   stages=p.stages)

    def _fail_chapter(self, p: "_ChapterPlan", stage: str,
                      exc: Exception, results: dict) -> None:
        p.errored = True
        self._emit("chapter_error",
                   chapter_id=p.chapter["id"],
                   stage=stage,
                   error=str(exc))
        self.sm.mark_chapter_status(
            p.chapter["id"], "error",
            error_message=f"[failed_stage:{stage}] {exc}"
        )
        results["error"] += 1

    def _complete_chapter(self, p: "_ChapterPlan", results: dict) -> None:
        ch_id      = p.chapter["id"]
        ch_row     = self.sm.get_chapter_by_id(ch_id) or {}
        audio_path = ch_row.get("output_audio_path", "")
        elapsed    = round(p.elapsed, 1)
        self.sm.mark_chapter_status(ch_id, "complete", processing_seconds=elapsed)
        self._emit("chapter_done",
                   chapter_id=ch_id,
                   audio_path=audio_path,
                   elapsed_s=elapsed)
        results["success"] += 1

    # ── Stage: LLM diarization ────────────────────────────────────────────────

    def _stage_diarize(self, director, chapter_id: int) -> float:
        """Diarize one chapter using an ALREADY-LOADED director. Returns elapsed s."""
        self._current_stage = "diarize"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="diarize")

        director.process_chapter(chapter_id)

        elapsed = round(time.time() - t0, 1)
        self._emit("stage_done", chapter_id=chapter_id, stage="diarize",
                   elapsed_s=elapsed)
        return elapsed

    # ── Stage: TTS synthesis ──────────────────────────────────────────────────

    def _stage_synthesize(self, engine, chapter_id: int) -> float:
        """Synthesize one chapter using an ALREADY-LOADED engine. Returns elapsed s."""
        self._current_stage = "synthesize"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="synthesize")

        def _tts_progress(lines_done: int, lines_total: int, line: dict) -> None:
            line = dict(line)  # sqlite3.Row compat
            self._emit("tts_progress",
                       chapter_id=chapter_id,
                       lines_done=lines_done,
                       lines_total=lines_total,
                       text=_truncate_live_text(line.get("text")),
                       speaker=line.get("speaker"),
                       emotion=line.get("emotion"))

        engine.process_chapter(chapter_id, progress_callback=_tts_progress)

        elapsed = round(time.time() - t0, 1)
        self._emit("stage_done", chapter_id=chapter_id, stage="synthesize",
                   elapsed_s=elapsed)
        return elapsed

    # ── Stage: Audio assembly ─────────────────────────────────────────────────

    def _stage_assemble(self, chapter_id: int) -> float:
        """Assemble one chapter's MP3 (CPU only). Returns elapsed s."""
        self._current_stage = "assemble"
        t0 = time.time()
        self._emit("stage_start", chapter_id=chapter_id, stage="assemble")

        asm = self._assembler_cls(
            self.sm,
            self.cfg.audio_mp3_dir,
            cfg={
                "output_format":        self.cfg.output_format,
                "min_completion_ratio": self.cfg.min_lines_threshold,
            },
        )
        asm.assemble_chapter(chapter_id)

        elapsed = round(time.time() - t0, 1)
        self._emit("stage_done", chapter_id=chapter_id, stage="assemble",
                   elapsed_s=elapsed)

        if self.cfg.cleanup_wavs:
            self._cleanup_chapter_wavs(chapter_id)
        return elapsed

    # ── VRAM barrier ──────────────────────────────────────────────────────────

    def _vram_barrier(self) -> None:
        """
        Polls VRAM usage after LLM unload until it returns to within
        _VRAM_DELTA_ALLOWANCE_MB of the pre-LLM baseline, or
        vram_wait_timeout_s expires.  Called between LLM exit and TTS enter.

        Delta-based: VRAM held by other apps is part of the baseline, so a
        browser using 2 GB does not stall the barrier or trigger warnings.
        """
        if not self.cfg.vram_check_enabled:
            return
        baseline  = self._vram_baseline_mb
        threshold = (baseline + _VRAM_DELTA_ALLOWANCE_MB
                     if baseline >= 0 else _VRAM_FALLBACK_THRESHOLD_MB)
        timeout  = self.cfg.vram_wait_timeout_s
        deadline = time.time() + timeout
        while True:
            used_mb = _query_vram_used_mb()
            if used_mb < 0:
                return  # nvidia-smi not available
            if used_mb <= threshold:
                print(f"[orch] VRAM barrier OK: {used_mb} MB used "
                      f"(baseline {baseline} MB, limit {threshold} MB).")
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                self._emit("vram_warning",
                           used_mb=used_mb,
                           threshold_mb=threshold,
                           baseline_mb=baseline)
                print(f"[orch] WARNING: {used_mb} MB VRAM still in use after "
                      f"{timeout}s wait (baseline {baseline} MB, limit "
                      f"{threshold} MB). TTS loading anyway — may OOM.")
                return
            print(f"[orch] VRAM barrier: {used_mb} MB used, want <= {threshold} MB, "
                  f"waiting ({remaining:.0f}s left)...")
            time.sleep(2)

    # ── Event emitter ─────────────────────────────────────────────────────────

    def _emit(self, event_type: str, **kwargs) -> None:
        event = {"type": event_type, "ts": time.time(), **kwargs}
        self.events.append(event)
        self.on_progress(event)
        _log_event(event)
        self._write_log(event)

    def _write_log(self, event: dict) -> None:
        if not self._log_file:
            return
        line = _format_log_line(event)
        if not line:
            return
        with self._log_lock:
            self._log_file.write(line + "\n")

    def _cleanup_chapter_wavs(self, chapter_id: int) -> None:
        wav_dir = Path(self.cfg.audio_wav_dir) / f"ch_{chapter_id:04d}"
        if not wav_dir.exists():
            return
        n_wavs = sum(1 for f in wav_dir.iterdir() if f.suffix == ".wav")
        shutil.rmtree(wav_dir)
        print(f"[orch] Cleaned {n_wavs} WAV(s) for chapter {chapter_id}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_log_line(event: dict) -> str:
    """Convert a pipeline event to a human-readable log line (empty = don't log)."""
    ts    = datetime.datetime.fromtimestamp(event.get("ts", time.time()))
    stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
    t     = event.get("type", "")

    if t == "pipeline_start":
        return (f"[{stamp}] PIPELINE START — "
                f"project={event.get('project')} total={event.get('total')}")
    if t in ("pipeline_done", "pipeline_stopped"):
        label = "DONE" if t == "pipeline_done" else "STOPPED"
        return (f"[{stamp}] PIPELINE {label} — "
                f"success={event.get('success')} "
                f"error={event.get('error')} "
                f"skipped={event.get('skipped')} "
                f"({event.get('elapsed_s')}s)")
    if t == "chapter_start":
        stages = ",".join(event.get("stages", []))
        return f"[{stamp}] CH {event.get('chapter_id', 0):04d} START — {stages}"
    if t == "chapter_done":
        path = Path(event.get("audio_path") or "").name
        return (f"[{stamp}] CH {event.get('chapter_id', 0):04d} COMPLETE "
                f"({event.get('elapsed_s')}s) -> {path}")
    if t == "chapter_error":
        return (f"[{stamp}] CH {event.get('chapter_id', 0):04d} ERROR "
                f"at {event.get('stage')}: {event.get('error')}")
    if t == "chapter_skip":
        return (f"[{stamp}] CH {event.get('chapter_id', 0):04d} SKIP "
                f"({event.get('reason')})")
    if t == "stage_start":
        return (f"[{stamp}] CH {event.get('chapter_id', 0):04d} "
                f">> {event.get('stage')}")
    if t == "stage_done":
        return (f"[{stamp}] CH {event.get('chapter_id', 0):04d} "
                f"<< {event.get('stage')} ({event.get('elapsed_s')}s)")
    if t == "model_load":
        return (f"[{stamp}] LOAD {str(event.get('model')).upper()} "
                f"({event.get('elapsed_s')}s) — amortised over "
                f"{event.get('chapters')} chapter(s)")
    if t == "vram_barrier":
        return f"[{stamp}] VRAM BARRIER ({event.get('elapsed_s')}s)"
    if t == "vram_warning":
        return (f"[{stamp}] VRAM WARNING: {event.get('used_mb')} MB used "
                f"(baseline {event.get('baseline_mb')} MB, "
                f"limit {event.get('threshold_mb')} MB)")
    return ""   # tts_progress and others are too noisy for the file log


def _query_vram_used_mb() -> int:
    """Returns VRAM used in MB on GPU 0 via nvidia-smi, or -1 on failure."""
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return -1


def _log_event(event: dict) -> None:
    t = event.get("type", "?")
    if t == "stage_start":
        print(f"[orch] >> Stage: {event.get('stage')} "
              f"(chapter {event.get('chapter_id')})")
    elif t == "stage_done":
        print(f"[orch] << Done:  {event.get('stage')} "
              f"in {event.get('elapsed_s')}s")
    elif t == "model_load":
        print(f"[orch] Loaded {event.get('model')} in {event.get('elapsed_s')}s "
              f"(amortised over {event.get('chapters')} chapter(s))")
    elif t == "vram_barrier":
        print(f"[orch] VRAM barrier cleared in {event.get('elapsed_s')}s")
    elif t == "chapter_done":
        print(f"[orch] Chapter {event.get('chapter_id')} complete "
              f"({event.get('elapsed_s')}s) -> {event.get('audio_path')}")
    elif t == "chapter_error":
        print(f"[orch] Chapter {event.get('chapter_id')} FAILED "
              f"at {event.get('stage')}: {event.get('error')}")
    elif t == "pipeline_done":
        print(f"[orch] Pipeline done in {event.get('elapsed_s')}s -- "
              f"success={event.get('success')} "
              f"error={event.get('error')} "
              f"skipped={event.get('skipped')}")
