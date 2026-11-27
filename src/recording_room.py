"""Execute a performance score: record batches, audition, checkpoint and reuse takes."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

from chapter_titles import identify
from performance_score import atomic_write, compile_score, write_json
from speech_audio import check_utterance, studio_pcm, concat_wavs
from state_manager import _resolve_stored_path
from speech_providers import provider_for
from take_review import TakeReviewer, compare_reading


class TakeShelf:
    """Bounded, disposable cache shared across editions. SQLite never points into it."""
    def __init__(self, root, limit=2 * 1024**3):
        self.root, self.limit = Path(root), limit

    def paths(self, key):
        base = self.root / key[:2] / key
        return base.with_suffix(".wav"), base.with_suffix(".json")

    def get(self, key):
        path, metadata = self.paths(key)
        try:
            meta = json.loads(metadata.read_text(encoding="utf-8"))
            audio = path.read_bytes()
            if hashlib.sha256(audio).hexdigest() != meta["sha256"]:
                return None
            path.touch()
            return audio, meta["audit"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key, audio, audit):
        path, metadata = self.paths(key)
        atomic_write(path, audio)
        write_json(metadata, {"sha256": hashlib.sha256(audio).hexdigest(), "audit": audit})

    def trim(self):
        files = sorted((p.stat().st_mtime_ns, p.stat().st_size, p)
                       for p in self.root.glob("*/*.wav"))
        total = sum(size for _, size, _ in files)
        for _, size, path in files:
            if total <= self.limit:
                break
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            total -= size


def emotion_baselines(sm, share=0.4, minimum=20):
    """Per character, emotions labelled so often they describe the voice, not a moment."""
    from collections import Counter, defaultdict
    from casting import choose_voice
    voices, counts = sm.get_voice_map(), defaultdict(Counter)
    for speaker, emotion, n in sm.emotion_counts_by_speaker():
        counts[choose_voice(speaker, "neutral", voices).canonical][emotion.casefold()] += n
    return {actor: {e for e, n in c.items() if e != "neutral" and n / sum(c.values()) > share}
            for actor, c in counts.items() if sum(c.values()) >= minimum}


class RecordingRoom:
    def __init__(self, sm, output_dir, model_dir, *, provider=None, reviewer=None):
        self.sm, self.root = sm, Path(output_dir).resolve()
        self.character_provider = None
        self.actor_providers = {}
        if provider is not None:
            self.narrator_provider = provider
        elif Path(model_dir).suffix == ".json" and _resolve_stored_path(model_dir).is_file():
            profile = json.loads(_resolve_stored_path(model_dir).read_text(encoding="utf-8"))
            providers = {}

            def renderer(path):
                directory = _resolve_stored_path(path).resolve()
                if directory not in providers:
                    providers[directory] = provider_for(sm, directory, self.root)
                return providers[directory]

            self.narrator_provider = renderer(profile["narrator"])
            self.character_provider = renderer(profile["characters"])
            self.actor_providers = {actor.casefold(): renderer(path)
                                    for actor, path in profile.get("actors", {}).items()}
        else:
            self.narrator_provider = provider_for(sm, model_dir, self.root)
        self.provider = self.narrator_provider
        baselines = emotion_baselines(sm)
        for provider in {self.narrator_provider, self.character_provider, *self.actor_providers.values()} - {None}:
            if hasattr(provider, "baselines"):
                provider.baselines = baselines
        self.reviewer = reviewer if reviewer is not None else TakeReviewer()
        self.shelf = TakeShelf(self.root / ".takes")
        self.stack = ExitStack()
        self.loaded = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def _record(self, cues, provider):
        jobs = [(cue, text) for cue in cues for text in cue.parts]
        speech = [(cue, text) for cue, text in jobs if any(c.isalnum() for c in text)]
        if speech and self.loaded and provider is not self.provider:
            self.stack.close()
            self.loaded = False
        if speech and not self.loaded:
            self.stack.enter_context(provider)
            self.provider = provider
            self.loaded = True
        rendered = []
        width = provider.batch_size
        for offset in range(0, len(speech), width):
            group = speech[offset:offset + width]
            batch = provider.render(group)
            if len(batch) != len(group):
                raise ValueError("Speech provider returned an incomplete batch.")
            rendered.extend(batch)
        takes = iter(rendered)
        result = []
        for cue in cues:
            pieces = []
            for text in cue.parts:
                if any(c.isalnum() for c in text):
                    audio = next(takes)
                    check_utterance(audio, text)
                else:
                    audio = provider.pause()
                pieces.append(studio_pcm(audio))
            result.append(pieces[0] if len(pieces) == 1 else concat_wavs(pieces))
        return result

    def process_chapter(self, chapter_id, progress_callback=None):
        rows = self.sm.get_lines_for_chapter(chapter_id)
        chapter = self.sm.get_chapter_by_id(chapter_id) or {}
        cues = compile_score(rows, self.sm.get_voice_map(), self.sm.get_pronunciations(),
                             heading=identify(chapter.get("title") or ""))
        folder = self.root / f"ch_{chapter_id:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        by_index = {c.index: row for c, row in zip(cues, rows)}
        partitions = {}
        records = {}
        for cue in cues:
            provider = self.actor_providers.get(cue.actor.casefold())
            if provider is None:
                provider = (self.character_provider if self.character_provider and cue.actor != "Narrator"
                            else self.narrator_provider)
            partitions.setdefault(provider, []).append(cue)
            identity = (provider.conditioning_identity(cue) if hasattr(provider, "conditioning_identity")
                        else provider.identity)
            records[cue.index] = {**cue.record(identity), "renderer": provider.name}
        score = {"schema": 1, "renderer": "Directed cast" if self.character_provider else self.provider.name,
                 "checkpoints": {p.name: p.identity for p in partitions},
                 "chapter_id": chapter_id, "cues": list(records.values())}
        write_json(folder / "score.json", score)
        count = 0
        for provider, group in self._batches(partitions):
            ready, missing = {}, []
            for cue in group:
                key = records[cue.index]["take_key"]
                hit = self.shelf.get(key)
                if hit:
                    if (hit[1]["status"] == "checked" and "heard" in hit[1]
                            and hit[1].get("version", 1) < TakeReviewer.version):
                        audit = {**hit[1], **compare_reading(cue.spoken, hit[1]["heard"]),
                                 "version": TakeReviewer.version}
                        if audit["review"] and not hit[1]["review"]:
                            missing.append(cue)
                            continue
                        hit = hit[0], audit
                        self.shelf.put(key, *hit)
                    if hit[1]["status"] == "not_checked" and not getattr(self.reviewer, "unavailable", False):
                        audit = self.reviewer.check(hit[0], cue.spoken)
                        if audit["review"]:
                            missing.append(cue)
                            continue
                        hit = hit[0], audit
                        if audit["status"] != "not_checked":
                            self.shelf.put(key, *hit)
                    ready[cue.index] = (*hit, True)
                else:
                    missing.append(cue)
            if missing:
                try:
                    first = self._record(missing, provider)
                except Exception:
                    if not self.loaded:
                        raise  # setup error, e.g. missing weights; retrying lines cannot help
                    first = [None] * len(missing)
                for cue, audio in zip(missing, first):
                    try:
                        if audio is None:
                            audio, = self._record([cue], provider)
                        audit = self.reviewer.check(audio, cue.spoken)
                        if audit["review"]:
                            # Keep a usable first take if the alternative fails or scores worse.
                            try:
                                alt, = self._record([cue], provider)
                                second = self.reviewer.check(alt, cue.spoken)
                                if (not second["review"], second["score"]) > (False, audit["score"]):
                                    audio, audit = alt, second
                            except (ValueError, RuntimeError, OSError):
                                pass
                            audit = {**audit, "retake": True}
                        self.shelf.put(records[cue.index]["take_key"], audio, audit)
                        ready[cue.index] = audio, audit, False
                    except Exception as exc:
                        self.sm.mark_line_failed(cue.line_id, str(exc))
                        raise RuntimeError(f"Line {cue.index} ({cue.speaker}): {exc}") from exc
            for cue in group:
                audio, audit, cached = ready[cue.index]
                path = folder / f"line_{cue.index:04d}.wav"
                atomic_write(path, audio)
                self.sm.mark_line_tts_done(cue.line_id, str(path))
                records[cue.index].update(audit=audit, cached=cached)
                count += 1
                if progress_callback:
                    progress_callback(count, len(cues), by_index[cue.index])
        write_json(folder / "score.json", score)
        self.shelf.trim()
        self.sm.mark_chapter_status(chapter_id, "tts_done")
        return count

    def _batches(self, partitions):
        # Record each model's assigned cast in one pass. The score retains book order.
        # For the next chapter, start with the model still in VRAM.
        for provider in sorted(partitions, key=lambda p: not (self.loaded and p is self.provider)):
            cues = partitions[provider]
            width = provider.batch_size
            for start in range(0, len(cues), width):
                yield provider, cues[start:start + width]
