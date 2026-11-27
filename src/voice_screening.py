"""Automatic defect screening for designed voice candidates (before anyone listens).

Three checks, all about defects rather than taste — the owner's blind votes showed that
acoustic similarity does not predict which voice he prefers (19 of 36 identity votes,
chance level), so ranking is left to his ears:

* words: the clip says its script (Whisper read-back), so the cloning transcript is exact;
* pitch: the median pitch fits the brief (a "boy about seven" must not come out as a man);
* distinctness: the voice is not nearly identical to someone already cast.
"""

import json
from pathlib import Path
import re

FEMALE = re.compile(r"\b(woman|female|girl|noblewoman|she|her)\b", re.I)
MALE = re.compile(r"\b(man|male|boy|nobleman|king|he|his)\b", re.I)
CHILD = re.compile(r"\b(child|kid|boy|girl)\b.*?\b(?:about|around)\s+(\w+)", re.I)
NUMBER_WORDS = {w: n for n, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
NONHUMAN = re.compile(r"\b(monster|creature|beast|inhuman)\b", re.I)
# Median f0 ranges (Hz) a voice of each kind should fall in; wide on purpose: they catch a
# wrong gender or a child voice that came out adult, not a style choice.
PITCH = {"male": (70, 200), "female": (150, 400), "child": (200, 500)}
TOO_CLOSE = 0.85  # resemblyzer cosine above which two voices are near-indistinguishable


def expected_profile(instruct):
    """'male' / 'female' / 'child' / None from a brief's wording (first sentence decides)."""
    first = re.split(r"(?<=[.;])\s", instruct, maxsplit=1)[0]
    if NONHUMAN.search(first):
        return None
    child = CHILD.search(first)
    if child:
        age = child.group(2).lower()
        age = int(age) if age.isdigit() else NUMBER_WORDS.get(age, 99)
        if age < 13:
            return "child"
    female, male = len(FEMALE.findall(first)), len(MALE.findall(first))
    return "female" if female > male else "male" if male > female else None


def median_f0(path):
    import librosa
    import numpy as np
    audio, rate = librosa.load(str(path), sr=16000)
    f0, voiced, _ = librosa.pyin(audio, fmin=60, fmax=500, sr=rate, frame_length=1024)
    values = f0[voiced & ~np.isnan(f0)]
    return float(np.median(values)) if values.size else None


def word_overlap(expected, heard):
    want = re.findall(r"[a-z']+", expected.lower())
    got = set(re.findall(r"[a-z']+", heard.lower()))
    return sum(w in got for w in want) / len(want) if want else 1.0


class Screener:
    def __init__(self, cast_voices):
        """cast_voices: {speaker: reference path} already in the cast, to keep new voices distinct."""
        from faster_whisper import WhisperModel
        from resemblyzer import VoiceEncoder, preprocess_wav
        self.asr = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
        self.encoder, self.prep = VoiceEncoder("cpu", verbose=False), preprocess_wav
        self.cast = {name: self._embed(path) for name, path in cast_voices.items() if Path(path).is_file()}

    def _embed(self, path):
        return self.encoder.embed_utterance(self.prep(str(path)))

    def check(self, wav, script, instruct, own_names=()):
        segments, _ = self.asr.transcribe(str(wav), language="en", beam_size=3, condition_on_previous_text=False)
        words = word_overlap(script, " ".join(s.text for s in segments))
        expected = expected_profile(instruct)
        f0 = median_f0(wav)
        low, high = PITCH.get(expected, (0, 10_000))
        pitch_ok = expected is None or f0 is None or low <= f0 <= high
        embedding = self._embed(wav)
        others = {n: float(embedding @ e) for n, e in self.cast.items() if n not in own_names}
        nearest = max(others, key=others.get) if others else None
        similarity = others.get(nearest, 0.0)
        distinct_ok = similarity < TOO_CLOSE
        return {"words": round(words, 3), "f0_hz": round(f0, 1) if f0 else None, "expected": expected,
                "pitch_ok": pitch_ok, "nearest": nearest, "similarity": round(similarity, 3),
                "distinct_ok": distinct_ok, "passed": words >= 0.85 and pitch_ok and distinct_ok}


def screen_candidates(screener, folder, own_names=()):
    """Screen every cand_N in a character's design folder; results saved beside them."""
    folder = Path(folder)
    results = {}
    for meta_path in sorted(folder.glob("cand_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        wav = meta_path.with_suffix(".wav")
        if not wav.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        results[meta_path.stem] = screener.check(wav, meta["reference_script"], meta["instruct"], own_names)
    (folder / "screening.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return results
