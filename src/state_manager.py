"""
Module 2: SQLite State Manager
================================
Owns the single source of truth for pipeline progress.
Every other module reads/writes state exclusively through this class.

INPUT contract  (from Module 1 epub_parser.py):
  ParsedBook / its dict equivalent — seeded via seed_project()

OUTPUT contracts:

  -> Module 3 (LLM Director) reads via get_chunks_for_chapter():
     [{ "id": int, "chapter_id": int, "chunk_index": int,
        "text": str, "word_count": int }]

  <- Module 3 writes via save_diarized_lines():
     [{ "line_index": int, "speaker": str, "text": str, "emotion": str }]

  -> Module 4 (TTS Engine) reads via get_pending_tts_lines():
     [{ "id": int, "chapter_id": int, "line_index": int,
        "speaker": str, "text": str, "emotion": str }]

  <- Module 4 writes via mark_line_tts_done(line_id, audio_path)

  -> Module 5 (Audio Assembler) reads via get_lines_for_chapter():
     [{ "id": int, "line_index": int, "audio_path": str }]

  -> Module 7 (FastAPI) reads via get_progress() / get_all_chapters():
     { "total": int, "pending": int, "diarized": int,
       "tts_done": int, "complete": int, "error": int }

Chapter status lifecycle:
  pending -> diarized -> tts_done -> assembled -> complete
                                              |-> error  (any stage)
"""

import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import asdict


# ── Valid status values ───────────────────────────────────────────────────────
CHAPTER_STATUSES = {"pending", "diarized", "tts_done", "assembled", "complete", "error"}
LINE_STATUSES    = {"pending", "tts_done", "failed"}

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    source_epub   TEXT    NOT NULL,
    total_chapters INTEGER NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_index INTEGER NOT NULL,
    title         TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    total_chunks  INTEGER NOT NULL DEFAULT 0,
    total_lines   INTEGER NOT NULL DEFAULT 0,
    output_audio_path TEXT,
    output_file_size_bytes INTEGER,
    error_message TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT    NOT NULL,
    word_count    INTEGER NOT NULL,
    UNIQUE(chapter_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    line_index    INTEGER NOT NULL,
    speaker       TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    emotion       TEXT    NOT NULL DEFAULT 'neutral',
    status        TEXT    NOT NULL DEFAULT 'pending',
    audio_path    TEXT,
    error_message TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(chapter_id, line_index)
);

CREATE TABLE IF NOT EXISTS voices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker       TEXT    NOT NULL UNIQUE,
    ref_audio_path TEXT   NOT NULL,
    ref_text      TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StateManager:
    """
    Thread-safe SQLite state manager for the audiobook pipeline.
    Uses WAL mode so the FastAPI backend can read while the pipeline writes.
    """

    def __init__(self, db_path: "str | Path" = "data/pipeline.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Internal ──────────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            for sql in [
                "ALTER TABLE chapters ADD COLUMN output_file_size_bytes INTEGER",
                "ALTER TABLE voices ADD COLUMN ref_text TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE chapters ADD COLUMN processing_seconds REAL",
            ]:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # column already exists

    # ── Project seeding ───────────────────────────────────────────────────────

    def seed_project(self, parsed_book, force_reseed: bool = False) -> int:
        """
        Import a ParsedBook (dataclass or dict) into the DB.

        Idempotent: if a project with the same source_epub already exists,
        returns its id without re-inserting unless force_reseed=True.

        Returns: project_id (int)
        """
        # Accept both dataclass and raw dict
        if hasattr(parsed_book, "__dataclass_fields__"):
            book = asdict(parsed_book)
        else:
            book = parsed_book

        name = Path(book["source_epub"]).stem

        with self._conn() as conn:
            if not force_reseed:
                row = conn.execute(
                    "SELECT id FROM projects WHERE name = ?", (name,)
                ).fetchone()
                if row:
                    print(f"[state] Project '{name}' already seeded (id={row['id']}). Skipping.")
                    return row["id"]

            # Upsert project
            conn.execute(
                """INSERT INTO projects (name, source_epub, total_chapters, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     total_chapters=excluded.total_chapters,
                     updated_at=excluded.updated_at""",
                (name, book["source_epub"], book["total_chapters"], _now()),
            )
            project_id = conn.execute(
                "SELECT id FROM projects WHERE name = ?", (name,)
            ).fetchone()["id"]

            for ch in book["chapters"]:
                conn.execute(
                    """INSERT INTO chapters
                         (project_id, chapter_index, title, total_chunks, status, updated_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)
                       ON CONFLICT(project_id, chapter_index) DO NOTHING""",
                    (project_id, ch["chapter_index"], ch["title"],
                     len(ch["chunks"]), _now()),
                )
                chapter_id = conn.execute(
                    """SELECT id FROM chapters
                       WHERE project_id=? AND chapter_index=?""",
                    (project_id, ch["chapter_index"]),
                ).fetchone()["id"]

                for ck in ch["chunks"]:
                    conn.execute(
                        """INSERT INTO chunks (chapter_id, chunk_index, text, word_count)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(chapter_id, chunk_index) DO NOTHING""",
                        (chapter_id, ck["chunk_index"], ck["text"], ck["word_count"]),
                    )

        print(f"[state] Seeded project '{name}' (id={project_id}, "
              f"{book['total_chapters']} chapters)")
        return project_id

    # ── Chapter queries ───────────────────────────────────────────────────────

    def get_project(self, name: str) -> "dict | None":
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_chapters(self, project_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM chapters
                   WHERE project_id = ?
                   ORDER BY chapter_index""",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapters_by_status(self, project_id: int, status: str) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM chapters
                   WHERE project_id = ? AND status = ?
                   ORDER BY chapter_index""",
                (project_id, status),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_chapter_status(
        self,
        chapter_id: int,
        status: str,
        audio_path: "str | None" = None,
        error_message: "str | None" = None,
        file_size_bytes: "int | None" = None,
        processing_seconds: "float | None" = None,
    ) -> None:
        if status not in CHAPTER_STATUSES:
            raise ValueError(f"Invalid chapter status: '{status}'. "
                             f"Valid: {CHAPTER_STATUSES}")
        with self._conn() as conn:
            conn.execute(
                """UPDATE chapters
                   SET status=?, output_audio_path=COALESCE(?,output_audio_path),
                       output_file_size_bytes=COALESCE(?,output_file_size_bytes),
                       error_message=COALESCE(?,error_message),
                       processing_seconds=COALESCE(?,processing_seconds),
                       updated_at=?
                   WHERE id=?""",
                (status, audio_path, file_size_bytes, error_message,
                 processing_seconds, _now(), chapter_id),
            )

    def delete_chapter_audio(self, chapter_id: int) -> bool:
        """Clear audio path/size from a completed chapter. Returns True if found."""
        with self._conn() as conn:
            n = conn.execute(
                """UPDATE chapters
                   SET output_audio_path=NULL, output_file_size_bytes=NULL, updated_at=?
                   WHERE id=?""",
                (_now(), chapter_id),
            ).rowcount
        return n > 0

    def reset_chapter_to_pending(self, chapter_id: int) -> bool:
        """Reset a chapter to pending, deleting all lines so it can be fully re-processed."""
        with self._conn() as conn:
            line_paths = [
                r["audio_path"] for r in conn.execute(
                    "SELECT audio_path FROM lines WHERE chapter_id=? AND audio_path IS NOT NULL",
                    (chapter_id,),
                ).fetchall()
            ]
            conn.execute("DELETE FROM lines WHERE chapter_id=?", (chapter_id,))
            n = conn.execute(
                """UPDATE chapters
                   SET status='pending', output_audio_path=NULL, output_file_size_bytes=NULL,
                       error_message=NULL, total_lines=0, processing_seconds=NULL, updated_at=?
                   WHERE id=?""",
                (_now(), chapter_id),
            ).rowcount
        for path in line_paths:
            p = Path(path)
            if p.exists():
                p.unlink()
        return n > 0

    # ── Chunk queries ─────────────────────────────────────────────────────────

    def get_chunks_for_chapter(self, chapter_id: int) -> list:
        """Returns chunks ordered by chunk_index. Read by Module 3 (LLM Director)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, chunk_index, text, word_count
                   FROM chunks WHERE chapter_id = ?
                   ORDER BY chunk_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Line writes (Module 3 output) ─────────────────────────────────────────

    def save_diarized_lines(self, chapter_id: int, lines: list) -> None:
        """
        Persist LLM diarization output for a chapter.
        Advances chapter status to 'diarized'.

        lines: [{ "line_index": int, "speaker": str,
                  "text": str, "emotion": str }]
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM lines WHERE chapter_id = ?", (chapter_id,))
            conn.executemany(
                """INSERT INTO lines (chapter_id, line_index, speaker, text, emotion)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (chapter_id, ln["line_index"], ln["speaker"],
                     ln["text"], ln.get("emotion", "neutral"))
                    for ln in lines
                ],
            )
            conn.execute(
                """UPDATE chapters
                   SET status='diarized', total_lines=?, updated_at=?
                   WHERE id=?""",
                (len(lines), _now(), chapter_id),
            )

    # ── Line queries (Module 4 TTS input/output) ──────────────────────────────

    def get_pending_tts_lines(self, chapter_id: int) -> list:
        """Lines not yet synthesised. Read by Module 4 (TTS Engine)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, line_index, speaker, text, emotion
                   FROM lines
                   WHERE chapter_id = ? AND status = 'pending'
                   ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lines_for_chapter(self, chapter_id: int) -> list:
        """All lines for a chapter. Read by Module 5 (Audio Assembler)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, line_index, speaker, text, emotion, status, audio_path, error_message
                   FROM lines WHERE chapter_id = ?
                   ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_line_tts_done(self, line_id: int, audio_path: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE lines SET status='tts_done', audio_path=? WHERE id=?""",
                (audio_path, line_id),
            )

    def mark_line_failed(self, line_id: int, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE lines SET status='failed', error_message=? WHERE id=?""",
                (error, line_id),
            )

    # ── Voice mapping ─────────────────────────────────────────────────────────

    def set_voice(self, speaker: str, ref_audio_path: str, ref_text: str = "") -> None:
        """Upsert a speaker -> reference audio mapping with optional transcript."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO voices (speaker, ref_audio_path, ref_text, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(speaker) DO UPDATE SET
                     ref_audio_path=excluded.ref_audio_path,
                     ref_text=excluded.ref_text,
                     updated_at=excluded.updated_at""",
                (speaker, ref_audio_path, ref_text, _now()),
            )

    def update_voice_ref_text(self, speaker: str, ref_text: str) -> bool:
        """Update only the transcript for an existing voice. Returns True if found."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE voices SET ref_text=?, updated_at=? WHERE speaker=?",
                (ref_text, _now(), speaker),
            )
            return cur.rowcount > 0

    def delete_voice(self, speaker: str) -> bool:
        """Remove a voice mapping. Returns True if found and deleted, False if not found."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM voices WHERE speaker = ?", (speaker,))
            return cur.rowcount > 0

    def get_voice_map(self) -> dict:
        """Returns { speaker: {"path": str, "ref_text": str} }. Read by Module 4 (TTS Engine)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT speaker, ref_audio_path, ref_text FROM voices"
            ).fetchall()
            return {
                r["speaker"]: {"path": r["ref_audio_path"], "ref_text": r["ref_text"] or ""}
                for r in rows
            }

    def get_all_voices(self) -> list:
        """Returns full voice rows for the UI."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM voices ORDER BY speaker"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Progress / stats ──────────────────────────────────────────────────────

    def get_progress(self, project_id: int) -> dict:
        """
        Returns aggregate progress for Module 7 (FastAPI) and the UI.

        Output:
        {
          "total": int,
          "pending": int,
          "diarized": int,
          "tts_done": int,
          "assembled": int,
          "complete": int,
          "error": int,
          "pct_complete": float
        }
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT status, COUNT(*) AS cnt
                   FROM chapters WHERE project_id = ?
                   GROUP BY status""",
                (project_id,),
            ).fetchall()

        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        complete = counts.get("complete", 0)
        return {
            "total":     total,
            "pending":   counts.get("pending", 0),
            "diarized":  counts.get("diarized", 0),
            "tts_done":  counts.get("tts_done", 0),
            "assembled": counts.get("assembled", 0),
            "complete":  complete,
            "error":     counts.get("error", 0),
            "pct_complete": round(complete / total * 100, 1) if total else 0.0,
        }

    def get_line_progress(self, chapter_id: int) -> dict:
        """Line-level progress for a chapter (used by live UI)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT status, COUNT(*) AS cnt
                   FROM lines WHERE chapter_id = ?
                   GROUP BY status""",
                (chapter_id,),
            ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        done = counts.get("tts_done", 0)
        return {
            "total":    total,
            "pending":  counts.get("pending", 0),
            "tts_done": done,
            "failed":   counts.get("failed", 0),
            "pct_done": round(done / total * 100, 1) if total else 0.0,
        }
