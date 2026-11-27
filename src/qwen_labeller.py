"""Local speaker / kind / emotion labelling with Qwen3 (llama.cpp), built for accuracy.

How a line is decided (each step only when the previous one leaves doubt):
1. Kind -- glyph-ambiguous spans (« », mixed or missing quote marks) and [brackets]
   are asked: speech, thought, telepathy, Spell notification or narration.
2. Speaker -- a multiple-choice question over a short candidate list built from the
   text's own evidence (attribution tags, pronoun antecedents, action beats, recent
   speakers, characters in the scene) plus "someone else". Asked twice: once with
   the recent speakers shown, once blind to them and with the options reversed, so
   the two answers cannot share a position bias or an earlier mistake.
3. Disagreement, or an answer that contradicts the text's gender evidence, gets a
   third ask in which Qwen reasons first (thinking mode). Still unresolved -> the
   line is decided but flagged for review.
4. Emotion -- one question with the narration's delivery words shown and neutral
   as the default.

Every question shares one prefix (rules, cast, previous-chapter tail, the whole
chapter), so llama.cpp evaluates the chapter once and each question costs only
its own few hundred tokens.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re

from attribution_evidence import Evidence, gather, new_names
from character_bible import NARRATOR, SPELL, UNNAMED_PREFIX, Bible
import label_prompts as P

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "Qwen3-14B-Q4_K_M.gguf"
LABELLER_VERSION = "qwen-v1"

_SPELL_TEXT = re.compile(r"^\[(?:You |Your |Ability|Attribute|Aspect|Memory|Echo|Rank|Class|Flaw|"
                         r"Shadow Core|Soul Core|Name:|Rank:|Class:|Congratulations)", re.I)
_DELIVERY = re.compile(
    r"\b(whisper\w*|murmur\w*|quietly|softly|under (?:his|her) breath|hush\w*|laugh\w*|chuckl\w*|"
    r"gigg\w*|grinn\w*|smil\w*|coldly|icy|icily|flatly|hollow\w*|emotionless(?:ly)?|even tone|calmly|"
    r"command\w*|order\w*|bark\w*|shout\w*|yell\w*|roar\w*|scream\w*|snap\w*|growl\w*|hiss\w*|"
    r"angr\w*|furious\w*|sigh\w*|sadly|sorrow\w*|trembl\w*|fear\w*|panic\w*|begg\w*|plead\w*|"
    r"desperat\w*|excit\w*|eager\w*|sarcas\w*|mock\w*|confus\w*|puzzl\w*|frown\w*|stern(?:ly)?|grim(?:ly)?)\b",
    re.I)


@dataclass
class Decision:
    index: int
    kind: str                  # speech | thought | telepathy | system | narration
    speaker: str
    gender: str = "unknown"
    emotion: str = "neutral"
    how: str = ""              # kind | agree | think | review
    votes: "list[str | None]" = field(default_factory=list)
    options: "list[str]" = field(default_factory=list)
    cues: "list[str]" = field(default_factory=list)
    review: "str | None" = None


class LocalModel:
    """Qwen3 GGUF via llama-cpp-python, driven with raw ChatML so the prefix cache holds."""

    def __init__(self, path: Path = DEFAULT_MODEL, n_ctx: int = 12288):
        from llama_cpp import Llama
        if not Path(path).exists():
            raise FileNotFoundError(f"Labelling model not found: {path}")
        # q8_0 KV cache halves its VRAM so a whole chapter fits beside the 9 GB weights.
        self.llm = Llama(model_path=str(path), n_gpu_layers=-1, n_ctx=n_ctx, n_batch=1024,
                         flash_attn=True, type_k=8, type_v=8, verbose=False)
        self.n_ctx = n_ctx
        self._grammars: dict[str, object] = {}

    def close(self) -> None:
        self.llm.close()

    def count(self, text: str) -> int:
        return len(self.llm.tokenize(text.encode("utf-8"), add_bos=False, special=True))

    def _grammar(self, choices: str):
        from llama_cpp import LlamaGrammar
        if choices not in self._grammars:
            self._grammars[choices] = LlamaGrammar.from_string(
                "root ::= " + " | ".join(f'"{c}"' for c in choices), verbose=False)
        return self._grammars[choices]

    @staticmethod
    def chat(system: str, user: str) -> str:
        return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"

    def _complete(self, prompt: str, **kwargs) -> str:
        tokens = self.llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
        if len(tokens) + kwargs.get("max_tokens", 1) >= self.n_ctx:
            raise ValueError(f"Prompt of {len(tokens)} tokens does not fit n_ctx={self.n_ctx}")
        return self.llm.create_completion(tokens, **kwargs)["choices"][0]["text"]

    def choose(self, system: str, user: str, choices: str, think: bool = False, budget: int = 900) -> "str | None":
        prompt = self.chat(system, user)
        if think:
            reasoning = self._complete(prompt + "<think>\n", max_tokens=budget, temperature=0.6, top_p=0.95,
                                       top_k=20, stop=["</think>"], seed=7)
            prompt += "<think>\n" + reasoning.strip() + "\n</think>\n\nAnswer: "
        else:
            prompt += "<think>\n\n</think>\n\n"
        answer = self._complete(prompt, max_tokens=1, temperature=0.0, grammar=self._grammar(choices)).strip()
        return answer if answer in choices else None

    def text(self, system: str, user: str, max_tokens: int = 24) -> str:
        prompt = self.chat(system, user) + "<think>\n\n</think>\n\n"
        return self._complete(prompt, max_tokens=max_tokens, temperature=0.0, stop=["\n"]).strip()


class Labeller:
    def __init__(self, model: LocalModel, bible: Bible, *, emotions: bool = True, always_think: bool = False):
        self.model, self.bible, self.emotions = model, bible, emotions
        # Reason on every line, not only on disagreements (slower; measured on the gold set).
        self.always_think = always_think
        self.system = P.system_prompt(bible)

    # ── chapter ──────────────────────────────────────────────────────────────
    def label_chapter(self, segments: "list[dict]", title: str, previous_tail: "list[str]") -> "list[dict]":
        evidence = gather(self.bible, segments)
        self._segments = segments
        self._new_names = new_names(self.bible, segments)
        chapter = self._fit(segments, title, previous_tail)
        paragraphs: dict[int, list[dict]] = {}
        for segment in segments:
            paragraphs.setdefault(segment.get("paragraph", segment["index"]), []).append(segment)
        decisions: list[Decision] = []
        recent: list[tuple[int, str]] = []
        for segment in segments:
            if segment["kind"] == "prose" and not segment.get("hint"):
                continue
            decision = self._decide(chapter, segment, evidence[segment["index"]], recent)
            if self.emotions and decision.kind in ("speech", "thought", "telepathy"):
                decision.cues = _delivery_cues(segment, paragraphs)
                decision.emotion = self._emotion(chapter, segment, decision.speaker, decision.cues)
            decisions.append(decision)
            if decision.kind in ("speech", "telepathy"):
                recent.append((segment["index"], decision.speaker))
                del recent[:-6]
        return [asdict(d) for d in decisions]

    def _fit(self, segments, title, previous_tail) -> str:
        """The chapter block, trimming the previous-chapter tail if the context is tight."""
        tail = list(previous_tail)
        while True:
            chapter = P.render_chapter(segments, title, tail)
            if self.model.count(self.system + chapter) < self.model.n_ctx - 1500 or not tail:
                return chapter
            tail = tail[len(tail) // 2 + 1:] if len(tail) > 1 else []

    def _ask(self, chapter: str, question: str, choices: str, think: bool = False) -> "str | None":
        # The question follows the chapter so every ask reuses the cached chapter prefix.
        return self.model.choose(self.system, chapter + "\n\n" + question, choices, think)

    # ── one line ─────────────────────────────────────────────────────────────
    def _decide(self, chapter: str, segment: dict, ev: Evidence, recent) -> Decision:
        kind = self._kind(chapter, segment)
        if kind == "narration":
            return Decision(segment["index"], kind, NARRATOR, how="kind")
        if kind == "system":
            return Decision(segment["index"], kind, SPELL, how="kind")
        return self._speaker(chapter, segment, ev, recent, kind)

    def _kind(self, chapter: str, segment: dict) -> str:
        if segment["kind"] == "system":
            if _SPELL_TEXT.match(segment["text"]):
                return "system"
            answer = self._ask(chapter, P.system_question(segment), "ABC")
            return P.SYSTEM_OPTIONS["ABC".index(answer)] if answer else "system"
        if segment.get("hint"):
            answer = self._ask(chapter, P.kind_question(segment, self._surroundings(segment)), "ABCDE")
            if answer:
                # A letter or file being read stays with the narrator (gold-set convention).
                return P.KIND_OPTIONS["ABCDE".index(answer)]
        return "thought" if segment["kind"] == "thought" else "speech"

    def _surroundings(self, segment: dict) -> str:
        """Whether a glyph-ambiguous line sits inside a spoken exchange or a run of thoughts:
        the neighbouring paragraphs' unambiguous quotes are the best evidence of its kind."""
        paragraph = segment.get("paragraph", segment["index"])
        near = [s for s in self._segments
                if abs(s.get("paragraph", s["index"]) - paragraph) <= 2 and s is not segment
                and s["kind"] in ("dialogue", "thought") and not s.get("hint")]
        speech = sum(s["kind"] == "dialogue" for s in near)
        thoughts = len(near) - speech
        if speech and not thoughts:
            return f"The {speech} clearly marked quote(s) around it are spoken dialogue."
        if thoughts and not speech:
            return f"The {thoughts} clearly marked quote(s) around it are inner thoughts."
        return ""

    def options(self, ev: Evidence, recent, kind: str) -> "list[str]":
        """Candidate speakers, likeliest first: evidence, recent speakers, the scene."""
        ranked = [ev.tag, ev.beat, *ev.antecedents]
        if kind != "thought":
            ranked += [name for _, name in reversed(recent)]
        ranked += ev.participants
        named = [n for n in dict.fromkeys(ranked) if n and n not in (NARRATOR, SPELL)
                 and not n.startswith(UNNAMED_PREFIX)]
        return named[:8] + ["@other"]

    def _speaker(self, chapter, segment, ev: Evidence, recent, kind: str) -> Decision:
        options = self.options(ev, recent, kind)
        thought = kind == "thought"
        order_a = _rotate(options[:-1], segment["index"]) + ["@other"]
        order_b = list(reversed(order_a[:-1])) + ["@other"]
        a = self._pick(chapter, segment, ev, order_a, recent, thought)
        b = self._pick(chapter, segment, ev, order_b, [], thought)
        votes = [a, b]
        decision = Decision(segment["index"], kind, a or "@other", options=options, votes=votes)
        conflict = self._gender_conflict(ev, a) if a == b else None
        if a == b and a is not None and not conflict and not self.always_think:
            decision.how = "agree"
        elif a and b and a != b:
            # Measured: full-list tiebreaks were right 61-82% of the time. A two-way question
            # about only the disputed pair, reasoned first, is an easier task for a 14B model.
            pair = [a, b] if segment["index"] % 2 else [b, a]
            c = self._pick(chapter, segment, ev, pair, [], thought, think=True)
            votes.append(c)
            decision.speaker = c or a
            decision.how = "pair"
            if c is None or self._gender_conflict(ev, c):
                decision.how = "review"
                decision.review = self._gender_conflict(ev, c) or f"Speaker unsure: votes {votes}"
        else:
            c = self._pick(chapter, segment, ev, order_a, [], thought, think=True)
            votes.append(c)
            decision.speaker = _final(votes)
            settled = c is not None and c in (a, b) and not self._gender_conflict(ev, c)
            decision.how = "think" if settled else "review"
            if not settled:
                decision.review = self._gender_conflict(ev, c) or f"Speaker unsure: votes {votes}"
        if decision.speaker == "@other":
            decision.speaker, decision.gender = self._unnamed(chapter, segment, ev)
        else:
            decision.gender = self.bible.gender(decision.speaker)
        return decision

    def _pick(self, chapter, segment, ev, order, recent, thought, think=False) -> "str | None":
        question = P.speaker_question(segment, ev, self.bible, order, recent, thought=thought)
        choices = P.letters(len(order))
        letter = self._ask(chapter, question, choices, think)
        return order[choices.index(letter)] if letter else None

    def _gender_conflict(self, ev: Evidence, speaker: "str | None") -> "str | None":
        if not speaker or speaker == "@other" or ev.gender not in ("male", "female"):
            return None
        gender = self.bible.gender(speaker)
        if gender in ("male", "female") and gender != ev.gender:
            return f"The narration's pronoun says {ev.gender}, but {speaker} is {gender}."
        return None

    def _unnamed(self, chapter, segment, ev: Evidence) -> "tuple[str, str]":
        if ev.unnamed:
            return ev.unnamed, ev.gender or "unknown"
        if ev.beat_unnamed:
            # The narration just showed this unnamed person acting ("Ling's dad smiled").
            return ev.beat_unnamed, ev.beat_gender or "unknown"
        reply = self.model.text(self.system, chapter + "\n\n" + P.unnamed_question(segment))
        description, _, gender = reply.partition("|")
        description = " ".join(description.split()[:3]).strip(" .\"'") or "speaker"
        gender = gender.strip().lower()
        gender = gender if gender in ("male", "female") else (ev.gender or "unknown")
        named = self.bible.resolve_description(description)
        if named:
            return named, self.bible.gender(named)
        for name in self._new_names:  # "old carel" -> Carel, a name the sheet lacks
            if name.lower() in description.lower():
                return name, gender
        return f"{UNNAMED_PREFIX} {description.lower()}", gender

    def _emotion(self, chapter, segment, speaker: str, cues: "list[str]") -> str:
        choices = P.letters(len(P.EMOTIONS))
        letter = self._ask(chapter, P.emotion_question(segment, _display(speaker), cues), choices)
        emotion = P.EMOTIONS[choices.index(letter)] if letter else "neutral"
        return gate_emotion(emotion, cues)


# The four emotions that change the Fish delivery must be backed by the narration's own
# words. A model reads 'laughing' into a grin or a playful character; a wrong cue is far
# more audible than a missed one (owner's ear: plain delivery beat over-acting).
_REQUIRED_CUES = {
    "whispers": re.compile(r"whisper|murmur|quiet|soft|breath|hush", re.I),
    "laughing": re.compile(r"laugh|chuckl|gigg", re.I),
    "cold": re.compile(r"cold|icy|icily|flat|emotionless|hollow", re.I),
    "commanding": re.compile(r"command|order|bark", re.I),
}


def gate_emotion(emotion: str, cues: "list[str]") -> str:
    required = _REQUIRED_CUES.get(emotion)
    if required and not any(required.search(cue) for cue in cues):
        return "neutral"
    return emotion


def _final(votes: "list[str | None]") -> str:
    """Majority of the votes; otherwise the reasoned (last) vote, unless it only says
    'someone else' while an earlier vote named a character."""
    cast = [v for v in votes if v]
    for vote in cast:
        if cast.count(vote) >= 2:
            return vote
    if cast and cast[-1] != "@other":
        return cast[-1]
    named = [v for v in cast if v != "@other"]
    return named[0] if named else "@other"


def _delivery_cues(segment: dict, paragraphs: "dict[int, list[dict]]") -> "list[str]":
    """Delivery words in the narration attached to a quote: its own paragraph's prose and
    the last sentence of the paragraph before. The quote's own words are never cues
    ("don't whisper" is content, not delivery)."""
    paragraph = segment.get("paragraph", segment["index"])
    narration = [s["text"] for s in paragraphs.get(paragraph, []) if s["kind"] == "prose"]
    before = [s for s in paragraphs.get(paragraph - 1, []) if s["kind"] == "prose"]
    if before and paragraphs[paragraph][0] is segment:
        narration.append(re.split(r"(?<=[.!?…])\s+", before[-1]["text"].strip())[-1])
    return sorted({m.group(0).lower() for m in _DELIVERY.finditer(" ".join(narration))})


def _rotate(items: "list[str]", by: int) -> "list[str]":
    if not items:
        return items
    k = by % len(items)
    return items[k:] + items[:k]


def _display(speaker: str) -> str:
    return speaker.replace(UNNAMED_PREFIX + " ", "the ") if speaker.startswith(UNNAMED_PREFIX) else speaker
