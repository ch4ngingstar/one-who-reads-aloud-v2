"""Compile the editable chapter script into immutable, renderer-independent cues."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from casting import choose_voice
from chapter_titles import is_heading_line
from spoken_text import spoken_reading, split_for_speech
from state_manager import _resolve_stored_path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False, suffix=".part") as stage:
        tmp = Path(stage.name)
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode())


@dataclass(frozen=True)
class Cue:
    line_id: int
    index: int
    speaker: str
    actor: str
    kind: str
    emotion: str
    source: str
    spoken: str
    reference: str
    reference_hash: str
    fallback: bool
    parts: tuple[str, ...]
    revision: int

    def key(self, renderer):
        return digest([2, renderer, self.actor, self.emotion, self.kind,
                       self.reference_hash, self.parts, (self.line_id, self.revision) if self.revision else None])

    def record(self, renderer):
        return {**asdict(self), "take_key": self.key(renderer)}


def compile_score(lines, voices, pronunciations, heading=None):
    """`heading` (a chapter_titles.ChapterIdentity) silences a first line that only repeats it."""
    references, cues = {}, []
    for position, line in enumerate(lines):
        source = line["text"]
        spoken = spoken_reading(source, line.get("spoken_override"), pronunciations)
        if position == 0 and heading is not None and is_heading_line(source, heading):
            spoken = ""  # a pause; the chapter's heading is not read, as in every other chapter
        choice = choose_voice(line["speaker"], line["emotion"], voices, variant=line.get("chapter_id"))
        stand_in = (line.get("attribution") or {}).get("voice_as")
        if choice.fallback and stand_in:
            # An uncast speaker (an unnamed soldier, Awakened Kim) borrows the gender-matched
            # stand-in chosen at labelling time instead of the narrator's voice.
            choice = choose_voice(stand_in, line["emotion"], voices, variant=line.get("chapter_id"))
        if not choice.path:
            raise ValueError(f"No voice registered for {line['speaker']}; register a narrator or cast voice.")
        if choice.fallback and "_default" not in voices and choice.canonical != "Narrator":
            raise ValueError(
                f"Line {line['line_index'] + 1} needs a voice for {line['speaker']}. "
                "Choose a registered character for this line or assign a default voice."
            )
        path = _resolve_stored_path(choice.path).resolve()
        if path not in references:
            with path.open("rb") as ref:
                references[path] = hashlib.file_digest(ref, "sha256").hexdigest()
        cues.append(Cue(line["id"], line["line_index"], line["speaker"], choice.canonical,
                        line.get("kind") or "prose", line["emotion"], source, spoken, str(path),
                        references[path], choice.fallback or choice.canonical == "_default",
                        tuple(split_for_speech(spoken, 350)),
                        line.get("take_revision", 0)))
    if not cues:
        raise ValueError("Chapter has no labelled lines to record.")
    return tuple(cues)
