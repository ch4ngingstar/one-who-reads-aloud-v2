"""Exact transcripts for cloning references: a script sidecar beats a cached ASR guess."""

from pathlib import Path

from performance_score import atomic_write


class ReferenceTranscripts:
    """Resolve the words spoken in a reference clip, caching ASR results by audio hash."""

    def __init__(self, cache_dir):
        self.cache = Path(cache_dir)
        self.asr = None

    def get(self, reference, reference_hash, actor="the speaker"):
        # Designed references ship their exact script beside the clip; an ASR guess
        # would only add errors to the cloning prompt.
        sidecar = Path(reference).with_suffix(".txt")
        if sidecar.is_file() and (exact := sidecar.read_text(encoding="utf-8").strip()):
            return exact
        target = self.cache / (reference_hash + ".txt")
        if target.is_file():
            return target.read_text(encoding="utf-8")
        if self.asr is None:
            from faster_whisper import WhisperModel
            self.asr = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        segments, _ = self.asr.transcribe(str(reference), language="en", beam_size=3,
                                          condition_on_previous_text=False)
        result = " ".join(s.text.strip() for s in segments).strip()
        if not result:
            raise ValueError(f"No speech detected in {actor}'s reference.")
        atomic_write(target, result.encode())
        return result

    def _model(self):
        if self.asr is None:
            from faster_whisper import WhisperModel
            self.asr = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        return self.asr

    def fitted(self, reference, reference_hash, actor="the speaker", max_seconds=18.0):
        """A clip no longer than max_seconds plus its exact words, cut where a sentence ends.

        Long references cost GPU memory quadratically in some encoders (a 30 s clip needs a
        5.8 GB Fish codec graph) without adding identity. The registered file is never
        modified: a trimmed copy is cached beside the transcripts.
        """
        import numpy as np
        import soundfile as sf

        if sf.info(str(reference)).duration <= max_seconds:
            return str(reference), self.get(reference, reference_hash, actor)
        clip = self.cache / f"{reference_hash}-max{max_seconds:g}s.wav"
        words_file = clip.with_suffix(".txt")
        if clip.is_file() and words_file.is_file():
            return str(clip), words_file.read_text(encoding="utf-8")
        segments, _ = self._model().transcribe(str(reference), language="en", beam_size=3,
                                               condition_on_previous_text=False, word_timestamps=True)
        cut, text = choose_cut(list(segments), max_seconds)
        if cut is None:
            raise ValueError(f"{actor}'s reference has no speech that fits in {max_seconds:g}s.")
        audio, rate = sf.read(str(reference), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)[:int(cut * rate)].copy()
        fade = min(len(audio), int(0.03 * rate))  # no click at the cut
        if fade:
            audio[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        self.cache.mkdir(parents=True, exist_ok=True)
        staging = clip.with_suffix(".part.wav")
        sf.write(str(staging), audio, rate, subtype="PCM_16")
        staging.replace(clip)
        atomic_write(words_file, text.encode())
        return str(clip), text

    def close(self):
        self.asr = None


def choose_cut(segments, max_seconds, tail=0.15, shortest=3.0):
    """Latest sentence end that fits, else latest word end; returns (seconds, words)."""
    limit = max_seconds - tail
    whole = [i for i, s in enumerate(segments) if shortest <= s.end <= limit]
    if whole:
        last = whole[-1]
        return segments[last].end + tail, " ".join(s.text.strip() for s in segments[:last + 1]).strip()
    words = [w for s in segments for w in (s.words or [])]
    fits = [i for i, w in enumerate(words) if shortest <= w.end <= limit]
    if fits:
        last = fits[-1]
        return words[last].end + tail, "".join(w.word for w in words[:last + 1]).strip()
    return None, ""
