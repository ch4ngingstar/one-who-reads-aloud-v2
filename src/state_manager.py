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
from collections import Counter
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

CREATE TABLE IF NOT EXISTS pronunciations (
    spelling TEXT PRIMARY KEY COLLATE NOCASE,
    reading TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker       TEXT    NOT NULL UNIQUE,
    ref_audio_path TEXT   NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Sound-design library: tagged ambience / sfx / music clips (mirrors voices).
CREATE TABLE IF NOT EXISTS sfx_assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tag           TEXT    NOT NULL UNIQUE,
    category      TEXT    NOT NULL,            -- 'ambience' | 'sfx' | 'music'
    audio_path    TEXT    NOT NULL,
    display_name  TEXT,
    loopable      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Per-chapter sound-design cues (scene ambience ranges / discrete sfx / music).
CREATE TABLE IF NOT EXISTS chapter_cues (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    cue_type      TEXT    NOT NULL,            -- 'scene' | 'sfx' | 'music'
    tag           TEXT    NOT NULL,
    line_start    INTEGER NOT NULL,
    line_end      INTEGER,                     -- scenes only
    at_anchor     TEXT,                        -- sfx only: 'start' | 'end'
    gain_db       REAL    NOT NULL DEFAULT -20,
    duration_s    REAL,                        -- music only
    source        TEXT    NOT NULL DEFAULT 'cloud',
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_chapter_cues_chapter ON chapter_cues(chapter_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Repo root (parent of src/). Legacy DB rows store paths relative to it; some
# CWD=src runs wrote the same relative paths under src/. Used to resolve both.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_stored_path(p: "str | Path") -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    root_candidate = _REPO_ROOT / path
    if root_candidate.exists():
        return root_candidate
    src_candidate = _REPO_ROOT / "src" / path
    return src_candidate if src_candidate.exists() else root_candidate


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
                "ALTER TABLE chapters ADD COLUMN processing_seconds REAL",
                # ref_text was only needed by Fish Speech; IndexTTS2 ignores it.
                "ALTER TABLE voices DROP COLUMN ref_text",
                # Sound design: 1 once the user has hand-edited a chapter's cues,
                # which then guards against an auto-import clobbering manual edits.
                "ALTER TABLE chapters ADD COLUMN cues_reviewed INTEGER NOT NULL DEFAULT 0",
                # Voice Foundry WS1: segment kind (dialogue/thought/system/prose).
                # segment_chunk() computes it then discards it, so it is recovered by
                # deterministic replay -- see scripts/backfill_line_kind.py. Deliberately
                # NULLable with no default: NULL means "not backfilled / did not reconcile",
                # which must stay distinguishable from a real kind. Never guess a value.
                "ALTER TABLE lines ADD COLUMN kind TEXT",
                "ALTER TABLE lines ADD COLUMN take_revision INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE lines ADD COLUMN spoken_override TEXT",
                "ALTER TABLE lines ADD COLUMN speaker_locked INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE lines ADD COLUMN review_reason TEXT",
                "ALTER TABLE lines ADD COLUMN attribution TEXT",
                # Real chapter identity: EPUB entries are numbered by position ("entry 141"
                # is Chapter 1994) and end with a contents page; see chapter_titles.py.
                "ALTER TABLE chapters ADD COLUMN chapter_number INTEGER",
                "ALTER TABLE chapters ADD COLUMN display_title TEXT",
                "ALTER TABLE chapters ADD COLUMN kind TEXT NOT NULL DEFAULT 'chapter'",
            ]:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # column already exists / already dropped
            self._fill_chapter_identity(conn)

    @staticmethod
    def _fill_chapter_identity(conn) -> int:
        """Give every chapter without one its real number, clean title and kind. Idempotent."""
        from chapter_titles import identify
        rows = conn.execute(
            """SELECT c.id, c.title,
                      (SELECT k.text FROM chunks k WHERE k.chapter_id = c.id
                       ORDER BY k.chunk_index LIMIT 1) AS first_text
               FROM chapters c WHERE c.display_title IS NULL"""
        ).fetchall()
        for row in rows:
            identity = identify(row["title"], row["first_text"] or "")
            conn.execute(
                "UPDATE chapters SET chapter_number = ?, display_title = ?, kind = ? WHERE id = ?",
                (identity.number, identity.display, identity.kind, row["id"]),
            )
        return len(rows)

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

        with self._conn() as conn:
            self._fill_chapter_identity(conn)
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

    def list_projects(self) -> list:
        """All projects (newest first) for the UI project picker."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_projects_with_progress(self) -> list:
        """All projects with embedded progress dict — one connection, two queries."""
        with self._conn() as conn:
            projects = [dict(r) for r in conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()]

            agg_rows = conn.execute(
                """SELECT project_id, status, COUNT(*) AS cnt
                   FROM chapters GROUP BY project_id, status"""
            ).fetchall()

        counts: dict[int, dict[str, int]] = {}
        for r in agg_rows:
            counts.setdefault(r["project_id"], {})[r["status"]] = r["cnt"]

        for p in projects:
            c = counts.get(p["id"], {})
            total    = sum(c.values())
            complete = c.get("complete", 0)
            p["progress"] = {
                "total":     total,
                "pending":   c.get("pending",   0),
                "diarized":  c.get("diarized",  0),
                "tts_done":  c.get("tts_done",  0),
                "assembled": c.get("assembled", 0),
                "complete":  complete,
                "error":     c.get("error",     0),
                "pct_complete": round(complete / total * 100, 1) if total else 0.0,
            }
        return projects

    def get_all_chapters(self, project_id: int) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM chapters
                   WHERE project_id = ?
                   ORDER BY chapter_index""",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_chapter_by_id(self, chapter_id: int) -> "dict | None":
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()
            return dict(row) if row else None

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
                       error_message=?,
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
            p = _resolve_stored_path(path)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass  # locked/unreadable file must not block the DB reset
        return n > 0

    def queue_chapter_retry(self, chapter_id: int) -> bool:
        """Queue the failed stage, preserving all existing direction and takes."""
        with self._conn() as conn:
            return conn.execute(
                """UPDATE chapters SET status=CASE
                       WHEN instr(error_message, '[failed_stage:assemble]') > 0 THEN 'tts_done'
                       WHEN instr(error_message, '[failed_stage:synthesize]') > 0 THEN 'diarized'
                       ELSE 'pending' END,
                       error_message=NULL, updated_at=?
                   WHERE id=? AND status='error'""", (_now(), chapter_id)
            ).rowcount == 1

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
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT id,line_index,text,speaker,speaker_locked,spoken_override,take_revision "
                "FROM lines WHERE chapter_id=?", (chapter_id,)).fetchall()
            by_position = {(r["line_index"], r["text"]): r for r in prior}
            old_counts = Counter(r["text"] for r in prior)
            new_counts = Counter(line["text"] for line in lines)
            by_text = {r["text"]: r for r in prior if old_counts[r["text"]] == new_counts[r["text"]] == 1}
            values = []
            for line in lines:
                old = by_position.get((line["line_index"], line["text"]), by_text.get(line["text"]))
                locked = old["speaker_locked"] if old else bool(line.get("speaker_locked"))
                speaker = old["speaker"] if old and locked else line["speaker"]
                override = old["spoken_override"] if old else line.get("spoken_override")
                # Retakes are keyed by line ID and revision. Preserve both on an
                # unambiguous match so a new direction pass keeps the chosen take.
                values.append((old["id"] if old else None, chapter_id, line["line_index"], speaker,
                               line["text"], line.get("emotion", "neutral"), line.get("kind"),
                               override, locked, old["take_revision"] if old else 0, line.get("review_reason"),
                               json.dumps(line["attribution"]) if line.get("attribution") else None))
            conn.execute("DELETE FROM lines WHERE chapter_id = ?", (chapter_id,))
            conn.executemany(
                """INSERT INTO lines (id, chapter_id, line_index, speaker, text, emotion, kind,
                   spoken_override, speaker_locked, take_revision, review_reason, attribution)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values,
            )
            conn.execute(
                """UPDATE chapters
                   SET status='diarized', total_lines=?, updated_at=?
                   WHERE id=?""",
                (len(lines), _now(), chapter_id),
            )

    # ── Line queries (Module 4 TTS input/output) ──────────────────────────────

    def repair_render_inputs(self, chapter_id: int) -> bool:
        """Recover missing WAVs on unfinished chapters. Keep every usable take."""
        with self._conn() as conn:
            rows = conn.execute("SELECT id, status, audio_path FROM lines WHERE chapter_id=?",
                                (chapter_id,)).fetchall()
            missing = [(r["id"],) for r in rows if r["status"] == "tts_done" and
                       (not r["audio_path"] or not _resolve_stored_path(r["audio_path"]).is_file())]
            if missing:
                conn.executemany("UPDATE lines SET status='pending', audio_path=NULL WHERE id=?", missing)
            return bool(missing) or any(r["status"] != "tts_done" for r in rows)

    def get_pending_tts_lines(self, chapter_id: int) -> list:
        """Lines not yet synthesised. Read by Module 4 (TTS Engine)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, line_index, speaker, text, emotion, kind
                   FROM lines
                   WHERE chapter_id = ? AND status IN ('pending', 'failed')
                   ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lines_for_chapter(self, chapter_id: int) -> list:
        """All lines for a chapter. Read by Module 5 (Audio Assembler)."""
        with self._conn() as conn:
            rows = conn.execute(
                    """SELECT id, line_index, speaker, text, emotion, kind, status, audio_path, error_message, take_revision, spoken_override, speaker_locked, review_reason, attribution
                   FROM lines WHERE chapter_id = ?
                   ORDER BY line_index""",
                (chapter_id,),
            ).fetchall()
            lines = [dict(r) for r in rows]
            for line in lines:
                if line["speaker_locked"]:
                    line["attribution"] = {"method": "manual", "cue_indices": []}
                    if line["review_reason"]:
                        line["review_reason"] = line["review_reason"].removesuffix("Speaker needs confirmation.").strip() or None
                elif line["attribution"]:
                    line["attribution"] = json.loads(line["attribution"])
            return lines

    def queue_recording(self, chapter_id: int, line_index: int | None = None, speaker: str | None = None,
                        reading: str | None = None):
        """Keep the current master playable until the next edition publishes."""
        with self._conn() as conn:
            if not conn.execute("SELECT 1 FROM lines WHERE chapter_id=?", (chapter_id,)).fetchone():
                raise ValueError("This chapter has no saved script.")
            if line_index is not None:
                changed = conn.execute(
                    "UPDATE lines SET take_revision=take_revision+1, speaker=COALESCE(?,speaker), "
                    "speaker_locked=CASE WHEN ? IS NULL THEN speaker_locked ELSE 1 END, "
                    # Choosing a speaker by hand settles a flagged line.
                    "review_reason=CASE WHEN ? IS NULL THEN review_reason ELSE NULL END, "
                    "spoken_override=CASE WHEN ? IS NULL THEN spoken_override ELSE NULLIF(?, '') END, "
                    "status='pending', error_message=NULL WHERE chapter_id=? AND line_index=?",
                    (speaker, speaker, speaker, reading, reading, chapter_id, line_index))
                if not changed.rowcount:
                    raise ValueError("Unknown line.")
            conn.execute("UPDATE chapters SET status='diarized', error_message=NULL, updated_at=? WHERE id=?",
                         (_now(), chapter_id))

    def has_current_labels(self, chapter_id: int, labeller: str = "qwen-v1") -> bool:
        """True when ``labeller`` produced this chapter's lines (label_import marks every
        chapter it stores, even one without quotes)."""
        with self._conn() as conn:
            current, = conn.execute("SELECT SUM(attribution LIKE ?) FROM lines WHERE chapter_id=?",
                                    (f'%"{labeller}:%', chapter_id)).fetchone()
            return bool(current)

    def confirm_speaker(self, chapter_id: int, line_index: int) -> None:
        """The labeller's speaker is right: lock it and clear the review flag.

        Unlike a recast this keeps the recorded take - nothing about the line changed."""
        with self._conn() as conn:
            changed = conn.execute(
                "UPDATE lines SET speaker_locked=1, review_reason=NULL WHERE chapter_id=? AND line_index=?",
                (chapter_id, line_index))
            if not changed.rowcount:
                raise ValueError("Unknown line.")

    def mark_line_tts_done(self, line_id: int, audio_path: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE lines SET status='tts_done', audio_path=?, error_message=NULL WHERE id=?""",
                (audio_path, line_id),
            )

    def mark_lines_tts_done(self, updates: "list[tuple[int, str]]") -> None:
        """Batch update multiple lines to tts_done in one connection.

        updates: [(line_id, audio_path), ...]
        """
        if not updates:
            return
        with self._conn() as conn:
            conn.executemany(
                "UPDATE lines SET status='tts_done', audio_path=?, error_message=NULL WHERE id=?",
                [(path, line_id) for line_id, path in updates],
            )

    def mark_line_failed(self, line_id: int, error: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE lines SET status='failed', error_message=? WHERE id=?""",
                (error, line_id),
            )

    # ── Voice mapping ─────────────────────────────────────────────────────────

    def get_pronunciations(self) -> dict[str, str]:
        with self._conn() as conn:
            return dict(conn.execute("SELECT spelling, reading FROM pronunciations ORDER BY spelling"))

    def set_pronunciation(self, spelling: str, reading: str) -> None:
        with self._conn() as conn:
            if reading:
                conn.execute("INSERT INTO pronunciations VALUES (?,?) ON CONFLICT(spelling) "
                             "DO UPDATE SET reading=excluded.reading", (spelling, reading))
            else:
                conn.execute("DELETE FROM pronunciations WHERE spelling=?", (spelling,))

    def set_voice(self, speaker: str, ref_audio_path: str) -> None:
        """Upsert a speaker -> reference audio mapping."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO voices (speaker, ref_audio_path, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(speaker) DO UPDATE SET
                     ref_audio_path=excluded.ref_audio_path,
                     updated_at=excluded.updated_at""",
                (speaker, ref_audio_path, _now()),
            )

    def delete_voice(self, speaker: str) -> bool:
        """Remove a voice mapping. Returns True if found and deleted, False if not found."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM voices WHERE speaker = ?", (speaker,))
            return cur.rowcount > 0

    def emotion_counts_by_speaker(self) -> list:
        """(speaker, emotion, count) over spoken lines, for per-character delivery baselines."""
        with self._conn() as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT speaker, emotion, COUNT(*) FROM lines "
                "WHERE kind IN ('dialogue', 'thought') GROUP BY speaker, emotion")]

    def get_voice_map(self) -> dict:
        """Returns { speaker: {"path": str} }. Read by Module 4 (TTS Engine)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT speaker, ref_audio_path FROM voices"
            ).fetchall()
            return {
                r["speaker"]: {"path": r["ref_audio_path"]}
                for r in rows
            }

    def get_all_voices(self) -> list:
        """Returns full voice rows for the UI."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, speaker, ref_audio_path, created_at, updated_at "
                "FROM voices ORDER BY speaker"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Sound-design library (sfx_assets) ─────────────────────────────────────

    def set_sfx_asset(
        self,
        tag: str,
        category: str,
        audio_path: str,
        display_name: "str | None" = None,
        loopable: bool = True,
    ) -> None:
        """Upsert a tag -> sound clip mapping (mirrors set_voice)."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sfx_assets
                     (tag, category, audio_path, display_name, loopable, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tag) DO UPDATE SET
                     category=excluded.category,
                     audio_path=excluded.audio_path,
                     display_name=excluded.display_name,
                     loopable=excluded.loopable,
                     updated_at=excluded.updated_at""",
                (tag, category, audio_path, display_name,
                 1 if loopable else 0, _now()),
            )

    def delete_sfx_asset(self, tag: str) -> bool:
        """Remove a sound asset. Returns True if found and deleted."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM sfx_assets WHERE tag = ?", (tag,))
            return cur.rowcount > 0

    def get_sfx_map(self) -> dict:
        """Returns { tag: {"path": str, "category": str, "loopable": bool} }.

        Read by the SoundDesigner at render time to resolve cue tags to clips.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tag, category, audio_path, loopable FROM sfx_assets"
            ).fetchall()
            return {
                r["tag"]: {
                    "path": r["audio_path"],
                    "category": r["category"],
                    "loopable": bool(r["loopable"]),
                }
                for r in rows
            }

    def get_all_sfx(self) -> list:
        """Returns full sfx rows for the UI, grouped by category then tag."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, tag, category, audio_path, display_name, loopable, "
                "created_at, updated_at FROM sfx_assets ORDER BY category, tag"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Per-chapter sound-design cues (chapter_cues) ──────────────────────────

    def replace_chapter_cues(self, chapter_id: int, cues: list) -> int:
        """Atomically replace all cues for a chapter. Returns rows written.

        cues: [{ "cue_type": 'scene'|'sfx'|'music', "tag": str,
                 "line_start": int, "line_end": int|None,
                 "at_anchor": 'start'|'end'|None, "gain_db": float,
                 "duration_s": float|None, "source": str }]
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM chapter_cues WHERE chapter_id = ?", (chapter_id,))
            conn.executemany(
                """INSERT INTO chapter_cues
                     (chapter_id, cue_type, tag, line_start, line_end,
                      at_anchor, gain_db, duration_s, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (chapter_id, c["cue_type"], c["tag"], c["line_start"],
                     c.get("line_end"), c.get("at_anchor"),
                     c.get("gain_db", -20.0), c.get("duration_s"),
                     c.get("source", "cloud"))
                    for c in cues
                ],
            )
        return len(cues)

    def get_cues_for_chapter(self, chapter_id: int) -> list:
        """All sound-design cues for a chapter, ordered by line then type.

        Read by the AudioAssembler/SoundDesigner; also surfaced to the UI.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, chapter_id, cue_type, tag, line_start, line_end,
                          at_anchor, gain_db, duration_s, source, created_at
                   FROM chapter_cues WHERE chapter_id = ?
                   ORDER BY line_start, cue_type""",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_chapter_cues(self, chapter_id: int) -> int:
        """Delete all cues for a chapter. Returns rows deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM chapter_cues WHERE chapter_id = ?", (chapter_id,)
            )
            return cur.rowcount

    def mark_cues_reviewed(self, chapter_id: int, reviewed: bool = True) -> None:
        """Flag a chapter's cues as user-edited (guards against auto-overwrite)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE chapters SET cues_reviewed=?, updated_at=? WHERE id=?",
                (1 if reviewed else 0, _now(), chapter_id),
            )

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
