"""A conservative offline read-back check, independent of the speech model."""

from difflib import SequenceMatcher
import io
import re


def compare_reading(expected, heard):
    def words(s):
        return re.findall(r"\w+", s.casefold().replace("’", "").replace("'", ""))
    a, b = words(expected), words(heard)
    diff = SequenceMatcher(None, a, b, autojunk=False)
    match = sum(n for _, _, n in diff.get_matching_blocks())
    score = (2 * match / (len(a) + len(b))) if a or b else 1.0
    gap = max((max(j-i, l-k) for op, i, j, k, l in diff.get_opcodes() if op != "equal"), default=0)
    # A dropped "no" can reverse a reply even when the rest matches perfectly.
    # Count contracted and expanded negatives alike so "can't"/"cannot" agree.
    def negatives(text):
        return len(re.findall(r"\b(?:no|not|never|cannot)\b|n['’]t\b", text.casefold()))

    negative_changed = negatives(expected) != negatives(heard)
    # A single fantasy name or contraction should not trigger repeated inference.
    suspect = negative_changed or (len(a) >= 4 and (score < .60 or gap >= 4)) or (bool(a) and not b)
    audit = {"heard": heard, "score": round(score, 3), "review": suspect}
    if negative_changed:
        audit["reason"] = "Check whether the recorded line added or dropped a negative."
    return audit


class TakeReviewer:
    version = 2
    def __init__(self):
        self.model = None
        self.unavailable = False

    def check(self, audio, spoken):
        if not any(c.isalnum() for c in spoken):
            return {"review": False, "status": "pause"}
        if self.model is None and not self.unavailable:
            try:
                from faster_whisper import WhisperModel
                self.model = WhisperModel("base", device="cpu", compute_type="int8",
                                          cpu_threads=4, local_files_only=True)
            except (ImportError, OSError, RuntimeError, ValueError):
                self.unavailable = True
        if self.unavailable:
            return {"review": False, "status": "not_checked"}
        segments, _ = self.model.transcribe(io.BytesIO(audio), language="en", beam_size=1,
                                            condition_on_previous_text=False)
        return {"status": "checked", "version": self.version,
                **compare_reading(spoken, " ".join(s.text.strip() for s in segments))}
