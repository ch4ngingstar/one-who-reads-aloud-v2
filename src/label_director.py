"""The app's labelling stage: Qwen labels, Gemma double-checks, the result is stored.

A drop-in for the old ``LLMDirector`` (same constructor, context manager and
``process_chapter``), so the orchestrator still loads a model once per batch of
chapters and keeps the GPU free before recording starts:

    with LabelDirector(model_path, sm) as director:
        for chapter_id in batch:
            director.process_chapter(chapter_id)     # Qwen, one chapter at a time
        failures = director.finish()                 # Qwen out, Gemma in, store all

Every chapter's labels are also written to data/labels/ as an audit trail - the same
files the command-line scripts produce - so a chapter can be re-imported or compared.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from character_bible import Bible
from label_import import import_chapter
from label_pipeline import GEMMA, Gemma, add_second_opinion, label_record
from qwen_labeller import DEFAULT_MODEL, LABELLER_VERSION, Labeller, LocalModel

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels" / LABELLER_VERSION
CHECKED = ROOT / "data" / "labels" / f"{LABELLER_VERSION}-checked"


def _labeller_model(model_path) -> Path:
    """The UI's LLM path when it is a Qwen3 GGUF; otherwise the measured default."""
    path = Path(model_path) if model_path else None
    if path and path.exists() and "qwen3" in path.name.lower():
        return path
    return DEFAULT_MODEL


def _file_name(record: dict) -> str:
    return f"ch_{record['chapter']}.json" if record.get("chapter") is not None else f"chapter_id_{record['chapter_id']}.json"


class LabelDirector:
    # Chapters still carrying an older labeller's lines are relabelled before recording.
    relabels_old_labels = True

    def __init__(self, model_path, sm, speakers=None, cfg=None, *, second_opinion: Path = GEMMA,
                 labels_dir: Path = LABELS, checked_dir: Path = CHECKED):
        self.sm = sm
        self.model_path = _labeller_model(model_path)
        self.second_opinion = Path(second_opinion)
        self.labels_dir, self.checked_dir = Path(labels_dir), Path(checked_dir)
        self.records: list[dict] = []
        self.model = self.labeller = self.con = None

    def __enter__(self) -> "LabelDirector":
        self.bible = Bible.load()
        self.con = sqlite3.connect(str(self.sm.db_path))
        self.model = LocalModel(self.model_path)
        self.labeller = Labeller(self.model, self.bible)
        return self

    def __exit__(self, *exc) -> bool:
        self._close_qwen()
        if self.con is not None:
            self.con.close()
            self.con = None
        return False

    def _close_qwen(self) -> None:
        if self.model is not None:
            self.model.close()
            self.model = self.labeller = None

    def process_chapter(self, chapter_id: int) -> int:
        """Label one chapter with Qwen; it is stored when the batch finishes."""
        record = label_record(self.labeller, self.con, chapter_id)
        self.records.append(record)
        _write(self.labels_dir / _file_name(record), record)
        return len(record["labels"])

    def finish(self) -> "dict[int, Exception]":
        """Second opinion for the whole batch, then store each chapter.

        Returns the chapters that could not be stored; the rest are 'diarized'."""
        self._close_qwen()  # both models never share the 12 GB card
        gemma = None
        if self.second_opinion.exists():
            gemma = Gemma(self.second_opinion)
        else:
            print(f"[labels] Second-opinion model missing ({self.second_opinion}); "
                  "lines are flagged only where Qwen's own votes split.")
        failures: dict[int, Exception] = {}
        voices = self.sm.get_voice_map()
        try:
            for record in self.records:
                try:
                    if gemma is not None:
                        add_second_opinion(gemma, self.bible, self.con, record)
                    _write(self.checked_dir / _file_name(record), record)
                    import_chapter(self.sm, self.con, record, voices)
                except Exception as error:  # one chapter must not sink the batch
                    failures[record["chapter_id"]] = error
        finally:
            if gemma is not None:
                gemma.close()
            self.records = []
        return failures


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)
