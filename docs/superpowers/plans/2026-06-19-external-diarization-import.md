# External Diarization Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user diarize chapters with any external source (cloud LLM / hand) and import speaker+emotion labels — landing the chapter at `status='diarized'` exactly as the local Qwen3-14B would, skipping the local LLM.

**Architecture:** A labels-only round-trip. Export re-runs the deterministic `segment_chunk()` over a chapter's stored DB chunks to a chapter-global indexed segment list; the formatter returns labels keyed by that index; import re-runs the *same* segmentation, applies labels by index through the *identical* enforcement net the LLM uses, and saves via `save_diarized_lines`. Text never round-trips through an untrusted channel (verbatim-from-EPUB). Zero orchestrator changes — it already skips the LLM stage for `diarized` chapters.

**Tech Stack:** Python 3.11 (stdlib + existing `state_manager`, `segmenter`, `llm_director`), FastAPI, plain-script test harness (`python tests/test_*.py`), Next.js/React for the UI section.

**Design doc:** `docs/superpowers/specs/2026-06-19-external-diarization-import-design.md`

---

## File Structure

- **Modify `src/llm_director.py`** — extract the body of `LLMDirector._merge_labels` into a module-level pure function `enforce_labels(segments, labels, allowed, line_offset=0)`; `_merge_labels` becomes a one-line wrapper. No behavior change.
- **Create `src/diarization_io.py`** — GPU-free core: `segment_chapter`, `build_export`, `build_system_prompt_text`, `validate_labels`, `import_labels`. No `llama_cpp` import. Target < 350 lines.
- **Create `scripts/diarize_io.py`** — CLI: `export`, `import`, `format-cloud` (guarded `anthropic`). Resumable.
- **Modify `src/api.py`** — `GET /api/chapters/{id}/segments`, `POST /api/chapters/{id}/labels`.
- **Create `tests/test_diarization_io.py`** — plain-script tests (temp SQLite, no GPU).
- **Modify `ui/.../InspectorPanel.tsx`** — "External diarization" section (export download + multi-file label upload).

---

## Task 1: Extract `enforce_labels` as a pure function (no behavior change)

**Files:**
- Modify: `src/llm_director.py:464-510` (`_merge_labels`)
- Test: existing `tests/test_llm_director.py` (regression lock — must stay 40/40)

- [ ] **Step 1: Run the existing suite to capture the green baseline**

Run: `python tests/test_llm_director.py`
Expected: `Results: 40 passed, 0 failed`

- [ ] **Step 2: Add the module-level `enforce_labels` function**

Insert immediately **above** the `LLMDirector` class definition (after `_fallback_lines` helpers / near the other module-level functions like `_allowed_speakers`). Move the exact body of `_merge_labels` into it, parameterising `self._allowed` as `allowed`:

```python
def enforce_labels(
    segments: "list[dict]",
    labels: "dict[int, tuple[str, str]]",
    allowed: "set[str]",
    line_offset: int = 0,
) -> "list[dict]":
    """Apply structural speaker enforcement and produce final line dicts.

    Shared by the LLM path (LLMDirector._merge_labels) and the external
    diarization importer (diarization_io) so both self-heal identically:
    prose -> Narrator (except genuine Sunny inner monologue), thought ->
    POV/Sunny, system -> roster-or-Spell, dialogue != Narrator -> Unknown,
    bad emotion -> neutral.
    """
    lines: list[dict] = []
    for seg in segments:
        speaker, emotion = labels[seg["index"]]
        kind, text = seg["kind"], seg["text"]

        if kind == KIND_PROSE:
            if not (speaker == "Sunny"
                    and not _is_narrator_misattribution("Sunny", text)):
                if speaker != "Narrator":
                    print(f"[llm]   FIX  prose '{speaker}' -> Narrator | {text[:60]!r}")
                speaker = "Narrator"
        elif kind == KIND_THOUGHT:
            if speaker not in allowed or speaker == SYSTEM_SPEAKER:
                speaker = "Sunny"
        elif kind == KIND_SYSTEM:
            if speaker not in allowed:
                speaker = SYSTEM_SPEAKER
        else:  # dialogue
            if speaker not in allowed or speaker == "Narrator":
                speaker = "Unknown"

        if emotion not in EMOTION_VOCAB:
            emotion = "neutral"

        lines.append({
            "line_index": line_offset + len(lines),
            "speaker":    speaker,
            "text":       text,
            "emotion":    emotion,
        })
    return lines
```

- [ ] **Step 3: Replace the `_merge_labels` body with a thin wrapper**

```python
    def _merge_labels(
        self,
        segments: "list[dict]",
        labels: "dict[int, tuple[str, str]]",
        line_offset: int,
    ) -> "list[dict]":
        """Apply structural speaker enforcement and produce final line dicts."""
        return enforce_labels(segments, labels, self._allowed, line_offset)
```

- [ ] **Step 4: Run the suite to verify the refactor is behavior-neutral**

Run: `python tests/test_llm_director.py`
Expected: `Results: 40 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add src/llm_director.py
git commit -m "refactor(llm): extract enforce_labels pure fn from _merge_labels"
```

---

## Task 2: `segment_chapter` — deterministic chapter-global segments

**Why first:** `segment_chunk` re-indexes from 0 per chunk. Export and import must agree on a single chapter-global index space; both call this one helper so they cannot drift.

**Files:**
- Create: `src/diarization_io.py`
- Test: `tests/test_diarization_io.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_diarization_io.py`:

```python
"""
Test suite for external diarization import (diarization_io.py).
Run: python tests/test_diarization_io.py
No GPU / no model required.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state_manager import StateManager
import diarization_io as dio


def _tmp_sm():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateManager(db_path=tmp.name)


def _seed_chapter(sm, text_chunks):
    book = {
        "source_epub": "test.epub",
        "total_chapters": 1,
        "chapters": [{
            "chapter_index": 7,
            "title": "Chapter 7",
            "chunks": [
                {"chunk_index": i, "text": t, "word_count": len(t.split())}
                for i, t in enumerate(text_chunks)
            ],
        }],
    }
    pid = sm.seed_project(book)
    ch_id = sm.get_all_chapters(pid)[0]["id"]
    return pid, ch_id


def test_segment_chapter_global_indices():
    sm = _tmp_sm()
    # two chunks, each yields >=1 segment; indices must be 0..N-1 across both
    _, ch_id = _seed_chapter(sm, ["The hall was silent.", '"Move out," she said.'])
    segs = dio.segment_chapter(sm, ch_id)
    assert [s["index"] for s in segs] == list(range(len(segs))), \
        "chapter-global indices must be contiguous 0..N-1"
    assert len(segs) >= 2, "expected at least one segment per chunk"
    assert all({"index", "kind", "text"} <= set(s) for s in segs)
    print("  PASS test_segment_chapter_global_indices")


TESTS = [
    test_segment_chapter_global_indices,
]


if __name__ == "__main__":
    print("Running diarization_io tests...\n")
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{'=' * 40}\nResults: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python tests/test_diarization_io.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'diarization_io'`

- [ ] **Step 3: Create `src/diarization_io.py` with `segment_chapter`**

```python
"""
External diarization I/O (Module 3 side-channel).

Lets a chapter be diarized OUTSIDE the local LLM: export its deterministic
segments, format speaker+emotion labels anywhere, import them back. Text is
NEVER trusted from the external source -- it is re-derived verbatim from the
stored EPUB chunks via segment_chunk(). GPU-free, no llama_cpp import.
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python tests/test_diarization_io.py`
Expected: `Results: 1 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add src/diarization_io.py tests/test_diarization_io.py
git commit -m "feat(diarization-io): chapter-global segment flattening"
```

---

## Task 3: `build_export` + `build_system_prompt_text`

**Files:**
- Modify: `src/diarization_io.py`
- Test: `tests/test_diarization_io.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_diarization_io.py` (above the `TESTS` list):

```python
def test_build_export_payload():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"We move at dawn." Nephis turned away.'])
    payload = dio.build_export(sm, ch_id)

    assert payload["chapter_id"] == ch_id
    assert payload["chapter_index"] == 7
    assert payload["title"] == "Chapter 7"
    assert "Narrator" in payload["speakers"] and "Unknown" in payload["speakers"]
    assert payload["speakers"][0] == "Narrator"
    segs = payload["segments"]
    assert [s["i"] for s in segs] == list(range(len(segs)))
    assert all({"i", "kind", "text"} == set(s) for s in segs)
    # text is verbatim-from-EPUB (a known fragment survives)
    assert any("We move at dawn" in s["text"] for s in segs)
    print("  PASS test_build_export_payload")


def test_build_export_unknown_chapter_raises():
    sm = _tmp_sm()
    try:
        dio.build_export(sm, 999)
        assert False, "expected ValueError for unknown chapter"
    except ValueError:
        pass
    print("  PASS test_build_export_unknown_chapter_raises")


def test_system_prompt_text_has_roster_and_schema():
    txt = dio.build_system_prompt_text()
    assert "Narrator" in txt and "Unknown" in txt
    assert '"labels"' in txt and '"speaker"' in txt and '"emotion"' in txt
    for emo in EMOTION_VOCAB:
        assert emo in txt
    print("  PASS test_system_prompt_text_has_roster_and_schema")
```

Add the three names to `TESTS`:

```python
    test_build_export_payload,
    test_build_export_unknown_chapter_raises,
    test_system_prompt_text_has_roster_and_schema,
```

- [ ] **Step 2: Run to verify failure**

Run: `python tests/test_diarization_io.py`
Expected: FAIL — `AttributeError: module 'diarization_io' has no attribute 'build_export'`

- [ ] **Step 3: Implement `build_export` and `build_system_prompt_text`**

Append to `src/diarization_io.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python tests/test_diarization_io.py`
Expected: `Results: 4 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add src/diarization_io.py tests/test_diarization_io.py
git commit -m "feat(diarization-io): export payload + external system prompt"
```

---

## Task 4: `validate_labels` + `import_labels` (the round-trip core)

**Files:**
- Modify: `src/diarization_io.py`
- Test: `tests/test_diarization_io.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_diarization_io.py` (above `TESTS`):

```python
def _all_labels(sm, ch_id, speaker="Narrator", emotion="neutral"):
    """Synthetic labels covering every segment index for a chapter."""
    segs = dio.segment_chapter(sm, ch_id)
    return {"chapter_id": ch_id,
            "labels": [{"i": s["index"], "speaker": speaker, "emotion": emotion}
                       for s in segs]}


def test_import_round_trip_sets_diarized():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent. Dust hung in the air."])
    labels = _all_labels(sm, ch_id, speaker="Narrator", emotion="calm")

    n = dio.import_labels(sm, ch_id, labels)

    chapter = sm.get_chapter_by_id(ch_id)
    assert chapter["status"] == "diarized"
    lines = sm.get_lines_for_chapter(ch_id)
    assert len(lines) == n > 0
    assert [ln["line_index"] for ln in lines] == list(range(len(lines)))
    assert all(ln["speaker"] == "Narrator" for ln in lines)  # prose -> Narrator
    print("  PASS test_import_round_trip_sets_diarized")


def test_import_enforcement_parity_with_llm():
    """Importer and LLMDirector._merge_labels must yield identical lines."""
    from llm_director import LLMDirector, _allowed_speakers, DEFAULT_SPEAKERS
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"Run!" he shouted. The shadow lunged.'])
    segs = dio.segment_chapter(sm, ch_id)
    # craft a label per segment: dialogue->Sunny, everything else->Nephis
    raw = {}
    for s in segs:
        raw[s["index"]] = ("Sunny" if s["kind"] == "dialogue" else "Nephis", "afraid")

    # LLM path (single chunk -> per-chunk index == global index, offset 0)
    director = LLMDirector(Path("fake.gguf"), sm, speakers=DEFAULT_SPEAKERS)
    expected = director._merge_labels(segs, raw, 0)

    # Importer path
    labels = {"chapter_id": ch_id,
              "labels": [{"i": s["index"],
                          "speaker": raw[s["index"]][0],
                          "emotion": raw[s["index"]][1]} for s in segs]}
    dio.import_labels(sm, ch_id, labels)
    got = [{"line_index": ln["line_index"], "speaker": ln["speaker"],
            "text": ln["text"], "emotion": ln["emotion"]}
           for ln in sm.get_lines_for_chapter(ch_id)]

    assert got == expected, f"parity broken:\n  llm={expected}\n  imp={got}"
    print("  PASS test_import_enforcement_parity_with_llm")


def test_import_stale_count_mismatch_rejected():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent. Dust hung in the air."])
    labels = _all_labels(sm, ch_id)
    labels["labels"].pop()  # one short -> stale
    try:
        dio.import_labels(sm, ch_id, labels)
        assert False, "expected stale-export rejection"
    except dio.ImportRejected as e:
        assert "re-export" in str(e).lower()
    print("  PASS test_import_stale_count_mismatch_rejected")


def test_import_index_gap_rejected():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent. Dust hung in the air."])
    labels = _all_labels(sm, ch_id)
    if len(labels["labels"]) >= 2:
        labels["labels"][1]["i"] = labels["labels"][0]["i"]  # duplicate index
    try:
        dio.import_labels(sm, ch_id, labels)
        assert False, "expected duplicate-index rejection"
    except dio.ImportRejected:
        pass
    print("  PASS test_import_index_gap_rejected")


def test_import_repairs_bad_speaker_and_emotion():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ['"Hello there," said the guard.'])
    segs = dio.segment_chapter(sm, ch_id)
    labels = {"chapter_id": ch_id,
              "labels": [{"i": s["index"], "speaker": "Gandalf", "emotion": "bored"}
                         for s in segs]}
    dio.import_labels(sm, ch_id, labels)
    lines = sm.get_lines_for_chapter(ch_id)
    # out-of-roster dialogue speaker -> Unknown; bad emotion -> neutral
    dlg = [ln for ln in lines if '"Hello there,"' in ln["text"]]
    assert dlg and dlg[0]["speaker"] == "Unknown"
    assert all(ln["emotion"] == "neutral" for ln in lines)
    print("  PASS test_import_repairs_bad_speaker_and_emotion")


def test_import_clobber_guard():
    sm = _tmp_sm()
    _, ch_id = _seed_chapter(sm, ["The hall was silent."])
    dio.import_labels(sm, ch_id, _all_labels(sm, ch_id))      # -> diarized
    sm.mark_chapter_status(ch_id, "complete")
    try:
        dio.import_labels(sm, ch_id, _all_labels(sm, ch_id))  # no force
        assert False, "expected clobber rejection past diarized"
    except dio.ImportRejected:
        pass
    # force overrides
    n = dio.import_labels(sm, ch_id, _all_labels(sm, ch_id), force=True)
    assert n > 0 and sm.get_chapter_by_id(ch_id)["status"] == "diarized"
    print("  PASS test_import_clobber_guard")
```

Add to `TESTS`:

```python
    test_import_round_trip_sets_diarized,
    test_import_enforcement_parity_with_llm,
    test_import_stale_count_mismatch_rejected,
    test_import_index_gap_rejected,
    test_import_repairs_bad_speaker_and_emotion,
    test_import_clobber_guard,
```

- [ ] **Step 2: Run to verify failure**

Run: `python tests/test_diarization_io.py`
Expected: FAIL — `AttributeError: module 'diarization_io' has no attribute 'ImportRejected'`

- [ ] **Step 3: Implement validation, the guard, and import**

Append to `src/diarization_io.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python tests/test_diarization_io.py`
Expected: `Results: 10 passed, 0 failed`

- [ ] **Step 5: Run the full Python suite (no regressions)**

Run: `python tests/test_llm_director.py` then `python tests/test_diarization_io.py`
Expected: 40 passed / 0 failed, then 10 passed / 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/diarization_io.py tests/test_diarization_io.py
git commit -m "feat(diarization-io): validate + import labels (round-trip core)"
```

---

## Task 5: CLI `scripts/diarize_io.py`

**Files:**
- Create: `scripts/diarize_io.py`

- [ ] **Step 1: Implement the CLI (manual-run tool, no unit test — mirrors `scripts/measure_swap_tax.py`)**

```python
"""
External diarization CLI: export segments, import labels, optional cloud format.

Run from repo root:
    python scripts/diarize_io.py export --project "Shadow Slave" --range 258 260
    python scripts/diarize_io.py format-cloud --in data/diar_export
    python scripts/diarize_io.py import --project "Shadow Slave" --in data/diar_export
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager       # noqa: E402
import diarization_io as dio                  # noqa: E402

DEFAULT_DB = ROOT / "src" / "data" / "pipeline.db"


def _ch_name(chapter_id: int) -> str:
    return f"ch_{chapter_id:04d}"


def _resolve_project(sm: StateManager, name: str) -> int:
    proj = sm.get_project(name)
    if proj is None:
        sys.exit(f"error: no project named {name!r}")
    return proj["id"]


def _chapters_in_range(sm, project_id, rng):
    chapters = sm.get_all_chapters(project_id)
    if rng:
        lo, hi = rng
        chapters = [c for c in chapters if lo <= c["chapter_index"] <= hi]
    return chapters


def cmd_export(args):
    sm = StateManager(db_path=args.db)
    pid = _resolve_project(sm, args.project)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "system_prompt.txt").write_text(
        dio.build_system_prompt_text(), encoding="utf-8")

    n = 0
    for ch in _chapters_in_range(sm, pid, args.range):
        dest = out / f"{_ch_name(ch['id'])}.segments.json"
        if dest.exists() and not args.force:
            continue
        payload = dio.build_export(sm, ch["id"])
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        n += 1
        print(f"exported {dest.name} ({len(payload['segments'])} segments)")
    print(f"\n{n} chapter(s) exported to {out}")


def cmd_import(args):
    sm = StateManager(db_path=args.db)
    _resolve_project(sm, args.project)  # validate project exists
    src = Path(args.in_dir)
    if not src.is_dir():
        sys.exit(f"error: {src} is not a directory")

    ok = bad = 0
    for label_file in sorted(src.glob("ch_*.labels.json")):
        chapter_id = int(label_file.name[len("ch_"):].split(".")[0])
        payload = json.loads(label_file.read_text(encoding="utf-8"))
        try:
            n = dio.import_labels(sm, chapter_id, payload, force=args.force)
            print(f"  OK   {label_file.name} -> {n} lines (diarized)")
            ok += 1
        except dio.ImportRejected as e:
            print(f"  SKIP {label_file.name}: {e}")
            bad += 1
    print(f"\n{ok} imported, {bad} rejected")
    sys.exit(1 if bad else 0)


def cmd_format_cloud(args):
    """Optional: call Anthropic to produce labels from exported segments."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        sys.exit("error: `pip install anthropic` and set ANTHROPIC_API_KEY to use format-cloud")
    import os
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    src = Path(args.in_dir)
    system_prompt = (src / "system_prompt.txt").read_text(encoding="utf-8")
    done = 0
    for seg_file in sorted(src.glob("ch_*.segments.json")):
        chapter_id = int(seg_file.name[len("ch_"):].split(".")[0])
        out_file = src / f"ch_{chapter_id:04d}.labels.json"
        if out_file.exists() and not args.force:
            continue
        payload = json.loads(seg_file.read_text(encoding="utf-8"))
        user_msg = "\n".join(
            f"{s['i']} [{s['kind'][0].upper()}] {s['text']}" for s in payload["segments"])
        resp = client.messages.create(
            model=args.model, max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text
        start, end = text.find("{"), text.rfind("}")
        labels = json.loads(text[start:end + 1])
        labels["chapter_id"] = chapter_id
        out_file.write_text(json.dumps(labels, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        done += 1
        print(f"formatted {out_file.name}")
    print(f"\n{done} chapter(s) formatted")


def main():
    p = argparse.ArgumentParser(description="External diarization import/export")
    p.add_argument("--db", default=str(DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export")
    pe.add_argument("--project", required=True)
    pe.add_argument("--range", nargs=2, type=int, metavar=("LO", "HI"))
    pe.add_argument("--out", default="data/diar_export")
    pe.add_argument("--force", action="store_true")
    pe.set_defaults(func=cmd_export)

    pi = sub.add_parser("import")
    pi.add_argument("--project", required=True)
    pi.add_argument("--in", dest="in_dir", default="data/diar_export")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_import)

    pc = sub.add_parser("format-cloud")
    pc.add_argument("--in", dest="in_dir", default="data/diar_export")
    pc.add_argument("--model", default="claude-opus-4-8")
    pc.add_argument("--force", action="store_true")
    pc.set_defaults(func=cmd_format_cloud)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the CLI help (no DB needed)**

Run: `python scripts/diarize_io.py --help`
Expected: usage text listing `export`, `import`, `format-cloud`.

- [ ] **Step 3: Commit**

```bash
git add scripts/diarize_io.py
git commit -m "feat(diarization-io): export/import/format-cloud CLI"
```

---

## Task 6: API endpoints

**Files:**
- Modify: `src/api.py` (add two routes; reuse the existing `get_sm` dependency)
- Test: `tests/test_api.py` (existing plain-script suite)

- [ ] **Step 1: Inspect the existing route + test conventions**

Run: `python -c "import re,sys; print('read src/api.py and tests/test_api.py for get_sm/dependency_overrides patterns')"`
Then read `src/api.py` (find `get_sm`, a `@app.get` chapter route, and the Pydantic-model style) and `tests/test_api.py` (find `app.dependency_overrides[get_sm]` and the `TestClient` helper). Mirror those exactly in the next steps.

- [ ] **Step 2: Write the failing API tests**

Add to `tests/test_api.py`, following its existing `_client()` / `dependency_overrides` helper (names below assume that helper seeds a `StateManager` and returns a `TestClient`; adapt to the file's actual helper):

```python
def test_get_chapter_segments():
    client, sm = _client_with_chapter(['"Go," she said. He ran.'])  # existing-style helper
    ch_id = sm.get_all_chapters(sm.list_projects()[0]["id"])[0]["id"]
    r = client.get(f"/api/chapters/{ch_id}/segments")
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_id"] == ch_id
    assert [s["i"] for s in body["segments"]] == list(range(len(body["segments"])))
    print("  PASS test_get_chapter_segments")


def test_post_chapter_labels_imports():
    client, sm = _client_with_chapter(["The hall was silent."])
    ch_id = sm.get_all_chapters(sm.list_projects()[0]["id"])[0]["id"]
    segs = client.get(f"/api/chapters/{ch_id}/segments").json()["segments"]
    body = {"chapter_id": ch_id,
            "labels": [{"i": s["i"], "speaker": "Narrator", "emotion": "calm"}
                       for s in segs]}
    r = client.post(f"/api/chapters/{ch_id}/labels", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "diarized"
    assert sm.get_chapter_by_id(ch_id)["status"] == "diarized"
    print("  PASS test_post_chapter_labels_imports")


def test_post_chapter_labels_conflict_past_diarized():
    client, sm = _client_with_chapter(["The hall was silent."])
    ch_id = sm.get_all_chapters(sm.list_projects()[0]["id"])[0]["id"]
    segs = client.get(f"/api/chapters/{ch_id}/segments").json()["segments"]
    body = {"chapter_id": ch_id,
            "labels": [{"i": s["i"], "speaker": "Narrator", "emotion": "calm"}
                       for s in segs]}
    client.post(f"/api/chapters/{ch_id}/labels", json=body)
    sm.mark_chapter_status(ch_id, "complete")
    r = client.post(f"/api/chapters/{ch_id}/labels", json=body)
    assert r.status_code == 409, r.text
    print("  PASS test_post_chapter_labels_conflict_past_diarized")
```

Register them in `test_api.py`'s `TESTS` list and add a `_client_with_chapter(text_chunks)` helper next to the existing client helper if one isn't already present (seed a one-chapter project exactly like `_seed_chapter` in `tests/test_diarization_io.py`, then build the `TestClient` with `app.dependency_overrides[get_sm] = lambda: sm`).

- [ ] **Step 3: Run to verify failure**

Run: `python tests/test_api.py`
Expected: FAIL — 404 for `/api/chapters/{id}/segments` (route not defined yet).

- [ ] **Step 4: Add the routes to `src/api.py`**

Near the other `/api/chapters/...` routes, add (Pydantic model placed with the other request models at the top of the file):

```python
import diarization_io as dio
from fastapi import HTTPException
from pydantic import BaseModel


class LabelEntry(BaseModel):
    i: int
    speaker: str
    emotion: str


class LabelsImport(BaseModel):
    chapter_id: int | None = None
    labels: list[LabelEntry]


@app.get("/api/chapters/{chapter_id}/segments")
def get_chapter_segments(chapter_id: int, sm: StateManager = Depends(get_sm)):
    try:
        return dio.build_export(sm, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/chapters/{chapter_id}/labels")
def post_chapter_labels(chapter_id: int, payload: LabelsImport,
                        force: bool = False,
                        sm: StateManager = Depends(get_sm)):
    body = {"chapter_id": chapter_id,
            "labels": [e.model_dump() for e in payload.labels]}
    try:
        n = dio.import_labels(sm, chapter_id, body, force=force)
    except dio.ImportRejected as e:
        msg = str(e)
        # clobber guard -> 409, everything else (stale/bad/absent) -> 400/404
        if "past diarized" in msg:
            raise HTTPException(status_code=409, detail=msg)
        if "no chapter" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"chapter_id": chapter_id, "lines": n, "status": "diarized"}
```

(Use whatever `StateManager`/`Depends`/`get_sm` imports already exist in `api.py`; don't duplicate imports.)

- [ ] **Step 5: Run to verify pass**

Run: `python tests/test_api.py`
Expected: all tests pass, including the three new ones.

- [ ] **Step 6: Commit**

```bash
git add src/api.py tests/test_api.py
git commit -m "feat(api): GET chapter segments + POST chapter labels (import)"
```

---

## Task 7: UI — InspectorPanel "External diarization" section

**Files:**
- Modify: `ui/` `InspectorPanel.tsx` (exact path: locate with the search in Step 1)
- Test: `ui` vitest if a sibling test exists; otherwise typecheck only

- [ ] **Step 1: Locate the file and the existing per-chapter API call style**

Run: `cd ui && git grep -n "api/chapters" src`
Expected: shows how the UI builds `/api/chapters/...` URLs (base URL, fetch wrapper). Mirror that wrapper below instead of raw `fetch` if one exists.

- [ ] **Step 2: Add the section (visible for `pending` / `diarized` chapters)**

Inside `InspectorPanel.tsx`, add a section that:

```tsx
{(chapter.status === "pending" || chapter.status === "diarized") && (
  <section className="mt-4 border-t border-zinc-800 pt-4">
    <h4 className="text-xs uppercase tracking-wide text-zinc-400">External diarization</h4>

    <a
      href={`${API_BASE}/api/chapters/${chapter.id}/segments`}
      download={`ch_${String(chapter.id).padStart(4, "0")}.segments.json`}
      className="mt-2 inline-block rounded bg-zinc-800 px-3 py-1 text-sm hover:bg-zinc-700"
    >
      Export segments
    </a>

    <label className="mt-2 block text-sm text-zinc-400">
      Upload labels (one or more ch_XXXX.labels.json):
      <input
        type="file"
        accept=".json"
        multiple
        className="mt-1 block text-xs"
        onChange={(e) => handleLabelUpload(e.target.files)}
      />
    </label>

    {labelStatus.map((s) => (
      <p key={s.name} className={s.ok ? "text-xs text-emerald-400" : "text-xs text-rose-400"}>
        {s.name}: {s.message}
      </p>
    ))}
  </section>
)}
```

With the handler (place near the component's other callbacks; `setLabelStatus`/`labelStatus` is a `useState<{name:string;ok:boolean;message:string}[]>([])`):

```tsx
async function handleLabelUpload(files: FileList | null) {
  if (!files) return;
  const results: { name: string; ok: boolean; message: string }[] = [];
  for (const file of Array.from(files)) {
    // ch_0258.labels.json -> 258
    const m = file.name.match(/ch_(\d+)\.labels\.json$/);
    if (!m) {
      results.push({ name: file.name, ok: false, message: "not a ch_XXXX.labels.json file" });
      continue;
    }
    const chapterId = parseInt(m[1], 10);
    try {
      const body = JSON.parse(await file.text());
      const res = await fetch(`${API_BASE}/api/chapters/${chapterId}/labels`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      results.push({
        name: file.name,
        ok: res.ok,
        message: res.ok ? `diarized (${data.lines} lines)` : data.detail ?? "failed",
      });
    } catch (err) {
      results.push({ name: file.name, ok: false, message: String(err) });
    }
  }
  setLabelStatus(results);
  onChapterChanged?.();  // refresh the chapter list so status flips to diarized
}
```

Use the component's existing `API_BASE`/fetch helper and chapter-refresh callback names — match what's already in the file rather than inventing `onChapterChanged` if a different prop exists.

- [ ] **Step 3: Typecheck**

Run: `cd ui && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Run UI tests if present**

Run: `cd ui && npm test`
Expected: pass (or "no tests" if none cover the panel).

- [ ] **Step 5: Commit**

```bash
git add ui
git commit -m "feat(ui): external diarization export/import in InspectorPanel"
```

---

## Final verification

- [ ] Run the full Python suite:

```bash
python tests/test_llm_director.py
python tests/test_diarization_io.py
python tests/test_api.py
python tests/test_epub_parser.py
```

Expected: all suites report `0 failed`.

- [ ] UI: `cd ui && npm run typecheck && npm test` — clean.
- [ ] Manual end-to-end (optional, needs a real DB): export a real chapter, hand-edit a `labels.json`, import it, confirm the chapter shows `diarized` in the UI and the orchestrator skips the LLM stage on next run.

---

## Self-Review notes (author)

- **Spec coverage:** labels-only round-trip (Tasks 2–4), enforce_labels refactor + parity lock (Tasks 1, 4), file formats segments/labels/system_prompt (Tasks 3, 5), import validation incl. stale/coverage/repair/clobber (Task 4), CLI export/import/format-cloud (Task 5), API GET segments + POST labels with 409 (Task 6), UI section (Task 7), GPU-free tests (Tasks 2–6). All spec sections map to a task.
- **Determinism guarantee:** export and import both go through `segment_chapter` → identical chapter-global index space; parity test (Task 4 Step 1) locks importer output to `_merge_labels`.
- **Type consistency:** `import_labels(sm, chapter_id, payload, *, force, speakers)` and `ImportRejected` used identically in tests, CLI, and API. Line dict `{line_index, speaker, text, emotion}` matches `save_diarized_lines`. Export segment key is `i`; internal segment key is `index` (converted in `build_export`).
- **Adapt-on-contact:** Tasks 6–7 depend on real symbol names in `src/api.py` and `InspectorPanel.tsx` (get_sm helper, API_BASE, refresh callback). Each of those steps says to read the file and mirror existing names rather than assume.
