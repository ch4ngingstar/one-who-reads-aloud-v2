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
