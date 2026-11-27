"""Package finished chapters into one audiobook file (.m4b) with chapter markers.

Audiobook apps (BookPlayer, Smart AudioBook Player, Apple Books, Voice) then show the
chapter list, remember the listening position and keep the playback speed per book —
none of which works across hundreds of separate chapter MP3s.

Only chapters marked complete whose audio file exists are included; chapters missing in
the requested range are reported, so a partial volume is never mistaken for a whole one.
AAC at 64 kb/s mono is transparent for 24 kHz speech (a 40-hour volume is ~1.2 GB). The
file is written under a temporary name and renamed when complete, so an interrupted
export (power cut) never leaves a broken .m4b behind.
"""

from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import threading
import time

from audio_assembler import volume_album
from chapter_titles import identify
from state_manager import _resolve_stored_path

BOOK_TITLE = "Shadow Slave"
AUTHOR = "Guiltythree"


class ExportError(ValueError):
    """A request that cannot produce a book (unknown project, nothing finished, gaps with strict)."""


def chapter_number(title):
    found = re.search(r"(?i)chapter\s+(\d+)", title or "")
    return int(found.group(1)) if found else None


def ffmeta_escape(value):
    return re.sub(r"([=;#\\\n])", r"\\\1", str(value))


def duration_ms(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return round(float(out) * 1000)


def _connect(db):
    return sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro", uri=True)


def project_album(db, project, book_title=BOOK_TITLE):
    row = _connect(db).execute("select name from projects where id = ?", (project,)).fetchone()
    if not row:
        raise ExportError(f"No project with id {project}")
    return volume_album(book_title, row[0])


def select_chapters(con, project, first=None, last=None):
    """Finished story chapters (and the synopsis, if recorded) in book order; unfinished ones listed."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(chapters)")}
    identity = "chapter_number, display_title, kind" if "kind" in columns else "NULL, NULL, NULL"
    rows = con.execute(f"select id, title, status, output_audio_path, {identity} from chapters "
                       "where project_id = ? order by chapter_index", (project,)).fetchall()
    chosen, missing = [], []
    for cid, title, status, audio, number, display, kind in rows:
        if kind is None:  # database not migrated yet: classify from the title
            parsed = identify(title)
            number, display, kind = parsed.number, parsed.display, parsed.kind
        if kind == "back":
            continue
        if kind == "front":
            if first is None and status == "complete" and audio and _resolve_stored_path(audio).is_file():
                chosen.append({"id": cid, "number": None, "title": display, "path": _resolve_stored_path(audio)})
            continue
        if number is None:
            continue
        if (first is not None and number < first) or (last is not None and number > last):
            continue
        path = _resolve_stored_path(audio) if audio else None
        if status == "complete" and path and path.is_file():
            chosen.append({"id": cid, "number": number, "title": display, "path": path})
        else:
            missing.append(f"{display} ({status})")
    return chosen, missing


def build_metadata(chapters, durations, album, author):
    lines = [";FFMETADATA1", f"title={ffmeta_escape(album)}", f"album={ffmeta_escape(album)}",
             f"artist={ffmeta_escape(author)}", f"album_artist={ffmeta_escape(author)}", "genre=Audiobook"]
    start = 0
    for chapter, length in zip(chapters, durations):
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={start + length}",
                  f"title={ffmeta_escape(chapter['title'])}"]
        start += length
    return "\n".join(lines) + "\n", start


def default_output(db, project, out_dir, first=None, last=None):
    album = project_album(db, project)
    span = f" ch{first or ''}-{last or ''}" if first or last else ""
    return Path(out_dir) / (re.sub(r"[^\w ,.-]", "", album) + span + ".m4b")


def export(db, project, out, first=None, last=None, cover=None, bitrate="64k", strict=False,
           book_title=BOOK_TITLE, author=AUTHOR, log=print):
    album = project_album(db, project, book_title)
    chapters, missing = select_chapters(_connect(db), project, first, last)
    if missing:
        log(f"{len(missing)} chapter(s) in range are not finished and are left out: "
            + ", ".join(missing[:10]) + (f" … and {len(missing) - 10} more" if len(missing) > 10 else ""))
        if strict:
            raise ExportError(f"strict: {len(missing)} unfinished chapter(s) in range; nothing exported")
    if not chapters:
        raise ExportError("No finished chapters to export yet")
    durations = [duration_ms(c["path"]) for c in chapters]
    metadata, total = build_metadata(chapters, durations, album, author)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        tmp = Path(tmp)
        (tmp / "chapters.txt").write_text(metadata, encoding="utf-8")
        (tmp / "inputs.txt").write_text("".join(
            "file '{}'\n".format(c["path"].resolve().as_posix().replace("'", r"'\''")) for c in chapters),
            encoding="utf-8")
        staged = tmp / "book.m4b"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(tmp / "inputs.txt"), "-i", str(tmp / "chapters.txt")]
        if cover:
            cmd += ["-i", str(cover)]
        cmd += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
        if cover:
            cmd += ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        cmd += ["-c:a", "aac", "-b:a", bitrate, "-ac", "1", "-movflags", "+faststart", "-f", "mp4", str(staged)]
        log(f"Encoding {len(chapters)} chapters ({total / 3.6e6:.1f} h) -> {out}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-300:]}")
        staged.replace(out)
    return {"chapters": len(chapters), "missing": len(missing), "hours": round(total / 3.6e6, 2),
            "file": str(out)}


class BookExports:
    """At most one background export per project; the latest outcome stays readable."""

    def __init__(self, out_dir, runner=export):
        self.out_dir = Path(out_dir)
        self._runner = runner
        self._jobs = {}
        self._lock = threading.Lock()

    def start(self, db, project):
        with self._lock:
            job = self._jobs.get(project)
            if job and job["state"] == "running":
                return dict(job)
            out = default_output(db, project, self.out_dir)
            job = {"state": "running", "project": project, "file": str(out), "started": time.time()}
            self._jobs[project] = job
        threading.Thread(target=self._run, args=(db, project, out), daemon=True,
                         name=f"book-export-{project}").start()
        return dict(job)

    def _run(self, db, project, out):
        try:
            outcome = {"state": "done", **self._runner(db, project, out, log=lambda *_: None)}
        except Exception as exc:  # surfaced to the UI; the thread must never die silently
            outcome = {"state": "error", "error": str(exc)}
        with self._lock:
            self._jobs[project] = {**self._jobs[project], **outcome, "finished": time.time()}

    def status(self, project):
        with self._lock:
            return dict(self._jobs.get(project) or {"state": "idle", "project": project})
