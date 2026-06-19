"""
External diarization I/O (Module 3 side-channel).

Lets a chapter be diarized OUTSIDE the local LLM: export its deterministic
segments, format speaker+emotion labels anywhere (cloud LLM / hand), import them
back. Text is NEVER trusted from the external source -- it is re-derived verbatim
from the stored EPUB chunks via segment_chunk(). GPU-free, no llama_cpp import.
"""
from __future__ import annotations

from segmenter import segment_chunk
from llm_director import (
    enforce_labels, _allowed_speakers, _build_system_prompt,
    DEFAULT_SPEAKERS, EMOTION_VOCAB,
)


def segment_chapter(sm, chapter_id: int) -> "list[dict]":
    """Flatten a chapter's stored chunks into one chapter-global segment list.

    Re-runs the deterministic segmenter over chunks (ordered by chunk_index)
    and reassigns a contiguous chapter-global ``index`` (0..N-1). Both export
    and import call this, so the index space is guaranteed identical.
    """
    chunks = sm.get_chunks_for_chapter(chapter_id)
    if not chunks:
        raise ValueError(f"No chunks found for chapter_id={chapter_id}")

    segments: list[dict] = []
    for chunk in chunks:
        for seg in segment_chunk(chunk["text"]):
            segments.append({
                "index": len(segments),
                "kind":  seg["kind"],
                "text":  seg["text"],
            })
    return segments


def _roster(speakers: "list[str] | None" = None) -> "list[str]":
    spk = speakers if speakers is not None else DEFAULT_SPEAKERS
    return ["Narrator", *spk, "Unknown", "The Nightmare Spell"]


def build_export(sm, chapter_id: int,
                 speakers: "list[str] | None" = None) -> dict:
    """Read-only export payload for one chapter (see design doc format)."""
    chapter = sm.get_chapter_by_id(chapter_id)
    if chapter is None:
        raise ValueError(f"No chapter with id={chapter_id}")

    segments = segment_chapter(sm, chapter_id)
    return {
        "chapter_id":    chapter_id,
        "chapter_index": chapter["chapter_index"],
        "title":         chapter["title"],
        "speakers":      _roster(speakers),
        "segments": [
            {"i": s["index"], "kind": s["kind"], "text": s["text"]}
            for s in segments
        ],
    }


def build_system_prompt_text(speakers: "list[str] | None" = None) -> str:
    """The instruction block an external formatter (cloud LLM / human) needs.

    Reuses the exact local system prompt (roster + emotion vocab + per-kind
    rules + output schema) so external labels match what enforce_labels accepts.
    """
    spk = speakers if speakers is not None else DEFAULT_SPEAKERS
    return _build_system_prompt(spk)


# Statuses a plain import may land on. Anything further requires force=True.
_OVERWRITABLE = {"pending", "diarized", "error"}


class ImportRejected(Exception):
    """Raised when an external label file is invalid or unsafe to apply."""


def validate_labels(payload: dict, segments: "list[dict]") -> "dict[int, tuple[str, str]]":
    """Structural validation; returns an index -> (speaker, emotion) map.

    Content (out-of-roster speaker / bad emotion) is NOT validated here -- it is
    repaired downstream by enforce_labels, exactly as the LLM path self-heals.
    """
    if not isinstance(payload, dict) or "labels" not in payload:
        raise ImportRejected("labels file missing 'labels' array")
    raw = payload["labels"]
    if not isinstance(raw, list):
        raise ImportRejected("'labels' must be a list")

    n = len(segments)
    if len(raw) != n:
        raise ImportRejected(
            f"label count {len(raw)} != segment count {n} -- stale export, re-export this chapter")

    mapping: dict[int, tuple[str, str]] = {}
    for entry in raw:
        try:
            i = int(entry["i"])
            speaker = str(entry["speaker"])
            emotion = str(entry["emotion"])
        except (KeyError, TypeError, ValueError) as e:
            raise ImportRejected(f"malformed label entry {entry!r}: {e}")
        if not (0 <= i < n):
            raise ImportRejected(f"label index {i} out of range 0..{n - 1}")
        if i in mapping:
            raise ImportRejected(f"duplicate label index {i}")
        mapping[i] = (speaker, emotion)

    missing = set(range(n)) - mapping.keys()
    if missing:
        raise ImportRejected(f"missing label indices: {sorted(missing)}")
    return mapping


def import_labels(sm, chapter_id: int, payload: dict, *,
                  force: bool = False,
                  speakers: "list[str] | None" = None) -> int:
    """Validate external labels, enforce, and persist as diarized lines.

    Returns the number of lines written. Raises ImportRejected on any guard.
    """
    chapter = sm.get_chapter_by_id(chapter_id)
    if chapter is None:
        raise ImportRejected(f"no chapter with id={chapter_id}")
    if not force and chapter["status"] not in _OVERWRITABLE:
        raise ImportRejected(
            f"chapter {chapter_id} status '{chapter['status']}' is past diarized; "
            f"pass force=True to overwrite")

    segments = segment_chapter(sm, chapter_id)
    mapping = validate_labels(payload, segments)
    allowed = _allowed_speakers(speakers if speakers is not None else DEFAULT_SPEAKERS)

    lines = enforce_labels(segments, mapping, allowed, line_offset=0)
    sm.save_diarized_lines(chapter_id, lines)
    return len(lines)
