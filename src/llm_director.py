"""
Module 3: LLM Director (Diarization, label-only two-pass)
=========================================================
Pass 1: segmenter.segment_chunk() splits chunk text deterministically into
        dialogue / system / prose segments (word loss structurally impossible).
Pass 2: this module asks a local LLM to label each segment with a speaker and
        emotion ONLY -- the LLM never reproduces text. Output is grammar-locked
        to a JSON schema with enum speakers/emotions, so invalid JSON, invalid
        speakers, and invalid emotions are impossible at the decoder.

RECOMMENDED MODEL: Qwen3-14B Q4_K_M (single file, ~9 GB VRAM)
  Download: hf download Qwen/Qwen3-14B-GGUF Qwen3-14B-Q4_K_M.gguf --local-dir models
  Fits RTX 4070 (12 GB) at n_ctx=8192. Thinking mode is disabled automatically
  (/no_think soft switch) when the filename contains "qwen3".

  FALLBACK: Qwen2.5-14B-Instruct Q4_K_M (3-part split) still works unchanged --
  pass the -00001-of-00003 file as model_path.

INSTALL llama-cpp-python with CUDA:
  pip install llama-cpp-python --extra-index-url \
    https://abetlen.github.io/llama-cpp-python/whl/cu124 --no-cache-dir

VRAM LIFECYCLE (Hardware Enforcer):
  Use as a context manager - the model is FULLY UNLOADED on __exit__.
  Never instantiate LLMDirector while the TTS engine is loaded.

  with LLMDirector(model_path, sm, speakers=SPEAKERS) as director:
      director.process_chapter(chapter_id)
  # <- model purged here, CUDA cache cleared

INPUT  (from Module 2 StateManager):
  sm.get_chunks_for_chapter(chapter_id)
  -> [{ "id": int, "chunk_index": int, "text": str, "word_count": int }]

OUTPUT (to Module 2 StateManager):
  sm.save_diarized_lines(chapter_id, lines)
  lines: [{ "line_index": int, "speaker": str, "text": str, "emotion": str }]
"""

import gc
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from llama_cpp import Llama
    from llama_cpp.llama_grammar import LlamaGrammar
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

from segmenter import (
    segment_chunk, KIND_DIALOGUE, KIND_THOUGHT, KIND_SYSTEM, KIND_PROSE,
)
from state_manager import StateManager

# ── Defaults for Shadow Slave ──────────────────────────────────────────────────
DEFAULT_SPEAKERS = [
    # Core cast (Sunny arc)
    "Sunny", "Nephis", "Cassie", "Effie", "Kai",
    "Morgan", "Luster", "Jet",
    # Rain arc cast
    "Rain", "Ray", "Aiko", "Fleur", "Tamar",
    # Recurring named characters
    "Mordret", "Roan", "Kim", "Asterion", "Julius",
    "Tyris", "Revel",
    # Post-Vol-9 speakers (added 2026-06-20 from eval_roster.py EPUB audit:
    # text occurrences Jest 698, Seishan 248, Helie 128, Beastmaster 105).
    "Jest", "Seishan", "Helie", "Beastmaster",
    # Post-Vol-8 speakers (added 2026-06-23 from vol9/10/11 EPUB audit, ranked by
    # speech-verb adjacency: Anvil 15, Eurys 15, Ki Song 12, Naeve 9 (+30 as the
    # epithet "Nightwalker"), Moonveil 7, Warden 7, Bloodwave 4). Voices resolve
    # via SPEAKER_ALIASES in tts_engine.py (Anvil->Lord Valor, etc.).
    "Anvil", "Ki Song", "Eurys", "Naeve", "Bloodwave", "Moonveil", "Warden",
    # Post-2300 recurring speakers given designed voices (2026-11-25 casting;
    # chapters where they appear beside dialogue: Aether 33, Madoc 24, Lonesome Howl 10).
    "Aether", "Madoc", "Lonesome Howl",
    # Round 3 (2026-11-25): unvoiced post-2300 speakers ranked by scripts/cast.py discover.
    "Azarax", "Yutra", "Little Ling", "Pill", "Noctis", "Tegrot", "Death Singer", "Beth", "Quentin",
]

# Non-roster speaker archetypes. The diarizer routes an UNNAMED / non-roster
# speaker to the best-fitting archetype (instead of the single flat "Unknown"),
# which the TTS engine maps to a distinct fallback voice. Order is irrelevant.
# These names are registered in the voice map and resolve directly.
NPC_ARCHETYPES = [
    "The Hardened Awakened",     # veteran soldiers, government hunters, guards
    "The Bureaucrat",            # academy instructors, officials, clerks
    "The Legacy Noble",          # Valor / Song clan members, aristocrats
    "The Dream Realm Wanderer",  # scavengers, Sleepers, desperate survivors
    "The Nightmare Abomination", # generic corrupted / monsters that speak
]

EMOTION_VOCAB = [
    "neutral", "whispers", "angry", "sad", "excited",
    "commanding", "frightened", "confused", "pleading",
    "cold", "laughing", "sarcastic", "desperate",
]

SYSTEM_SPEAKER = "The Nightmare Spell"

_KIND_TAGS = {KIND_DIALOGUE: "D", KIND_THOUGHT: "T", KIND_SYSTEM: "S", KIND_PROSE: "P"}

# ── LLM generation config ──────────────────────────────────────────────────────
_DEFAULT_CFG = {
    # n_ctx=8192 verified safe for 14B Q4_K_M on RTX 4070 (12 GB):
    #   model weights ~8.5-9 GB + KV cache ~1.25 GB < 12 GB.
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "flash_attn":   True,
    "verbose":      False,
    # Qwen3 non-thinking guidance discourages pure greedy decoding; low temp +
    # top_p keeps labels near-deterministic without repetition pathologies.
    "temperature":  0.2,
    "top_p":        0.8,
    # Labels are ~22 tokens each; 4096 covers ~180 segments per chunk.
    "max_tokens":   4096,
    "retry_temp":   0.5,
    "max_retries":  3,
    "no_think":     None,   # None = auto-detect from model filename; True/False to force
}

# ── System prompt ──────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You label pre-split segments of the "Shadow Slave" web novel for a multi-voice \
audiobook. You NEVER output text -- only one speaker and one emotion label per segment.

== SEGMENT KINDS ==
[D] dialogue -- words spoken aloud by a character. Label with the speaker's name.
[T] thought  -- inner monologue of the scene's point-of-view character. Label with that
    character: Sunny in Sunny-POV scenes, Rain in Rain-POV scenes, etc. NEVER Narrator.
[P] prose    -- narration, description, actions, attribution tails ("he said"). Label Narrator.
[S] system   -- [bracketed] Nightmare Spell notification. Label The Nightmare Spell.

== SPEAKERS (use EXACTLY these names, nothing else) ==
{speakers}

== NPC ARCHETYPES (for UNNAMED / non-roster speakers -- pick the best fit) ==
{archetypes}
Use an archetype ONLY when the speaker is not a named roster character above. Match by role:
- The Hardened Awakened  : soldiers, hunters, guards, mercenaries, veteran fighters.
- The Bureaucrat         : officials, academy instructors, clerks, administrators, hosts.
- The Legacy Noble       : clan members & aristocrats (Valor, Song, Ki, the great houses).
- The Dream Realm Wanderer: scavengers, Sleepers, slaves, desperate survivors.
- The Nightmare Abomination: monsters, demons, the corrupted, hostile entities that speak.
When none clearly fits an unnamed speaker -> Unknown.

== EMOTIONS ==
{emotions}

== ATTRIBUTION RULES ==
A1 Attribution tails name the speaker. In `1 [D] Wait, / 2 [P] Sunny said`, segment 1 is Sunny.
A2 With no tail, follow conversation flow: two characters in a scene usually alternate turns.
A3 Roster names are for NAMED roster characters only. For an unnamed or non-roster
   speaker (guard, stranger, crowd member, servant, soldier, official, monster), pick the
   best-fitting NPC archetype; if none fits -> Unknown. NEVER pick a roster name just
   because that character is mentioned nearby -- an introduced-but-unlisted name (e.g.
   "Riven") is NOT a roster member -> archetype or Unknown.
A4 [P] segments are Narrator. ONE exception: a [P] segment that is clearly Sunny's direct
   inner thought, phrased in first person ("Why me?", "I have to run.") may be labeled Sunny.
   Third-person prose about Sunny ("Sunny walked...", "He sighed...") is ALWAYS Narrator.
A5 [S] segments: Nightmare Spell notifications ("You have slain...", "Your shadow grows
   stronger...") -> The Nightmare Spell. But brackets are ALSO used for telepathic rune
   messages between characters -- if the surrounding prose shows a character sending or
   answering ("Cassie's voice sounded in her mind: [...]"), label the SENDER instead.
   A mere stat or item readout the narrator would read ([1591/6000]) -> Narrator.
A6 [T] segments belong to whoever the scene follows. The thought may mention other people
   in third person ("She has been gone a month...") -- it is still the POV character's
   thought, NOT Narrator and NOT the person mentioned.

== EMOTION GUIDE ==
Choose every line's emotion from that line's own words and the prose around it.
The lists below are each character's plausible RANGE -- they tell you which
emotions suit that character, NEVER which one to apply by default. A character
does not have a "usual tone" you may fall back on. With no cue in the text, use
neutral for that line only.
Narrator : neutral, frightened or desperate in horror and battle, excited at revelations
Sunny    : neutral, sarcastic, confused, cold -- stoic, rarely openly emotional
Nephis   : neutral, cold, commanding -- always composed
Cassie   : neutral, sad, pleading -- gentle, soft-spoken
Effie    : neutral, excited, confused -- energetic
Kai      : neutral, commanding -- calm, professional
ANTI-SKEW RULE: never give one character the same emotion on most of their lines.
If a speaker has many lines in a chapter and nearly all carry a single emotion,
that output is WRONG -- re-read and judge each line on its own evidence. A whole
chapter of one character sounding commanding, or cold, or excited, is a failure.
Dialogue emotion follows the words AND the manner-cue in the attribution around it.
- A manner-cue in the [P] segment right before or after a [D] line sets that line's tone:
  "whispered"/"murmured"/"hushed" -> whispers; "shouted"/"barked"/"roared" -> angry or
  excited; "pleaded"/"begged" -> pleading; "said coldly"/"hissed" -> cold. The cue usually
  sits in the PREVIOUS or NEXT prose segment, NOT inside the spoken words -- carry it onto
  the [D] line instead of defaulting to the speaker's usual tone.
- questions -> confused ONLY when the speaker is genuinely uncertain or seeking an answer.
  A rhetorical, rote, or commanding question takes the tone the surrounding scene
  establishes (a cold threat phrased as a question stays cold; a calm clarifying question
  stays neutral).
- threats -> cold or angry; shouting -> angry or excited; hushed speech -> whispers.

== EPITHET GLOSSARY (later volumes name characters by TITLE -- map the title to the name) ==
Sunny: Sunless, Lord of Shadows, the Shadow, Sir/Detective Sunless, Devil of Antarctica.
Nephis: Changing Star, the Saint of Light, Lady Nephis.
Cassie: Song of the Fallen, the Seer, Saint Cassia. Effie: Athena, Raised by Wolves.
Kai: Nightingale. Jet: Soul Reaper, Boss. Morgan: Princess/Saint Morgan.
Mordret: Prince of Nothing (his "Reflections" / "Other Mordret" -> Mordret).
Anvil: King of Swords, Lord/King Valor. Ki Song: Queen of Beasts, Queen of Song.
Eurys: Eurys of the Nine. Naeve: the Nightwalker, Saint Naeve. Revel: the Dirge.
Tyris: Sky Tide. Tamar: Lady Tamar. The Nightmare Spell: the Weaver, the System.
A title resolves to the roster name; if the title belongs to nobody on the roster, treat
the speaker as an NPC archetype or Unknown -- never invent a new roster name.

== EXAMPLE 1 ==
Input:
0 [P] Sunny stared at the runes, his expression unreadable.
1 [D] What does it mean?
2 [P] he asked quietly. Nephis turned to face him.
3 [D] Power. Limitless power.
4 [S] [You have slain a Great Demon.]
5 [T] So that's what the runes were hiding all along...
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"Sunny","emotion":"confused"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"Nephis","emotion":"cold"}},
{{"i":4,"speaker":"The Nightmare Spell","emotion":"cold"}},
{{"i":5,"speaker":"Sunny","emotion":"cold"}}]}}

== EXAMPLE 2 (non-roster speakers -> archetype or Unknown) ==
Input:
0 [P] The guards exchanged uneasy glances.
1 [D] Who goes there?
2 [P] one of them demanded sharply.
3 [D] Your name?
4 [P] Sunny asked. The man straightened his coat.
5 [D] Riven. You can call me Riven.
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"The Hardened Awakened","emotion":"commanding"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"Sunny","emotion":"cold"}},
{{"i":4,"speaker":"Narrator","emotion":"neutral"}},
{{"i":5,"speaker":"Unknown","emotion":"neutral"}}]}}
Note: the unnamed guard is a soldier -> The Hardened Awakened. "Riven" introduces himself
but is NOT in the roster and his role is unclear -> Unknown, never a new roster name.

== EXAMPLE 3 (manner-cue carries onto the spoken line) ==
Input:
0 [P] Cassie leaned close and whispered into his ear.
1 [D] They are watching us. Say nothing.
2 [P] Sunny gave a slow nod, then asked evenly.
3 [D] How many?
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"Cassie","emotion":"whispers"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"Sunny","emotion":"neutral"}}]}}
Note: the "whispered" cue sits in the PREVIOUS [P] segment -> carry it onto line 1. Line 3
is a calm clarifying question ("asked evenly") -> neutral, NOT confused.

== EXAMPLE 4 (epithet -> roster name; unnamed -> archetype) ==
Input:
0 [P] The Changing Star regarded the soldier coldly.
1 [D] Report. How many did we lose?
2 [P] The grizzled veteran lowered his head.
3 [D] Thirty, my Saint. The Hollows broke through the eastern wall.
Output:
{{"labels":[
{{"i":0,"speaker":"Narrator","emotion":"neutral"}},
{{"i":1,"speaker":"Nephis","emotion":"commanding"}},
{{"i":2,"speaker":"Narrator","emotion":"neutral"}},
{{"i":3,"speaker":"The Hardened Awakened","emotion":"frightened"}}]}}
Note: "Changing Star" is the epithet for Nephis -> Nephis. The unnamed veteran soldier ->
The Hardened Awakened (not Unknown, not a roster name).

== OUTPUT ==
Return ONLY this JSON object, with exactly one label per input segment, in order:
{{"labels":[{{"i":0,"speaker":"...","emotion":"..."}}]}}"""


def _build_system_prompt(speakers: "list[str]") -> str:
    roster = ["Narrator"] + list(speakers) + ["Unknown", SYSTEM_SPEAKER]
    return _SYSTEM_PROMPT.format(
        speakers="\n".join(roster),
        archetypes="\n".join(NPC_ARCHETYPES),
        emotions=", ".join(EMOTION_VOCAB),
    )


def _allowed_speakers(speakers: "list[str]") -> "set[str]":
    return {"Narrator", "Unknown", SYSTEM_SPEAKER, *NPC_ARCHETYPES, *speakers}


def _ordered_grammar(count: int, actors) -> str:
    """Constrain the wire format and indices; the model chooses only the labels."""
    literal = lambda s: json.dumps(s, ensure_ascii=False)
    def choices(values):
        return " | ".join(literal(json.dumps(s, ensure_ascii=False)) for s in sorted(values))
    entries = [literal('{"i":' + str(i) + ',"speaker":') + ' actor ' +
               literal(',"emotion":') + ' emotion ' + literal('}') for i in range(count)]
    root = 'root ::= ' + literal('{"labels":[') + ' ' + (' ' + literal(',') + ' ').join(entries) + ' ' + literal(']}')
    return "\n".join([root, "actor ::= " + choices(actors), "emotion ::= " + choices(EMOTION_VOCAB)])


def _label_json_schema(speakers: "list[str]") -> dict:
    return {
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i":       {"type": "integer"},
                        "speaker": {"enum": sorted(_allowed_speakers(speakers))},
                        "emotion": {"enum": EMOTION_VOCAB},
                    },
                    "required": ["i", "speaker", "emotion"],
                },
            },
        },
        "required": ["labels"],
    }


# ── Response parsing ───────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> str:
    """Strip markdown fences and extract the first JSON object from text."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip()

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise ValueError("Unterminated JSON object in response")

    return text[start : end + 1]


def _parse_labels(response_text: str, n_segments: int) -> "dict[int, tuple[str, str]]":
    """
    Parse the LLM response into {segment_index: (speaker, emotion)}.
    Raises ValueError when any segment index is missing -- triggers a retry.
    """
    data = json.loads(_extract_json_block(response_text))
    if "labels" not in data or not isinstance(data["labels"], list):
        raise ValueError(f"Response missing 'labels' array. Got keys: {list(data.keys())}")

    labels: dict[int, tuple[str, str]] = {}
    for item in data["labels"]:
        if not isinstance(item, dict):
            raise ValueError("Expected a speaker label object")
        idx = item.get("i")
        if type(idx) is not int or not 0 <= idx < n_segments or idx in labels:
            raise ValueError(f"Invalid or duplicate segment index: {idx!r}")
        speaker = item.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"Missing speaker on segment {idx}")
        emotion = str(item.get("emotion", "neutral"))
        if emotion not in EMOTION_VOCAB:
            emotion = "neutral"
        labels[idx] = (speaker, emotion)

    missing = [i for i in range(n_segments) if i not in labels]
    if missing:
        raise ValueError(f"Labels missing for segment indices {missing[:8]} "
                         f"({len(missing)}/{n_segments} unlabeled)")
    return labels


# ── Inner-monologue guard (prose -> Sunny only) ────────────────────────────────

# First-/second-person markers that signal a genuine direct thought.
_DIALOGUE_PERSON_MARKERS = frozenset({
    "i", "i'm", "i'll", "i've", "i'd", "me", "my", "mine", "myself",
    "we", "we're", "we'll", "we've", "us", "our", "ours", "ourselves",
    "you", "you're", "you'll", "you've", "your", "yours", "yourself",
    "yourselves", "let's",
})

# Third-person actor pronouns: their presence (without any first/second-person
# marker) in a sentence of real length is a strong narration signal.
_THIRD_PERSON_ACTORS = frozenset({
    "he", "she", "they", "him", "her", "them", "his", "their", "its",
})

# Min word count before a bare third-person pronoun counts as narration.
_NARRATION_MIN_WORDS = 6


def _is_narrator_misattribution(speaker: str, text: str) -> bool:
    """
    Heuristic: does this text read as third-person narration ABOUT the speaker
    rather than something the speaker would say/think in first person?

    Used as the guard on the prose->Sunny inner-monologue exception: a prose
    segment the LLM labeled "Sunny" is only kept when this returns False.
    """
    if not text or not speaker or speaker in ("Narrator", "Unknown"):
        return False

    words = text.split()
    if not words:
        return False

    speaker_lower = speaker.lower()
    first_word = words[0].rstrip(",.!?:;").lower()

    # Rule 1 -- first word is the speaker's name / possessive.
    if first_word in (speaker_lower, speaker_lower + "'s"):
        return True

    # Rule 2 -- first word is a third-person pronoun.
    if first_word in _THIRD_PERSON_ACTORS:
        return True

    lower_words = [w.strip(",.!?:;\"'“”‘’()").lower() for w in words]

    # Genuine first/second-person speech or thought -- never reclassify.
    if any(w in _DIALOGUE_PERSON_MARKERS for w in lower_words):
        return False

    # Rule 3 -- the speaker narrated by their own name in third person.
    if speaker_lower in lower_words:
        return True

    # Rule 4 -- a real-length sentence driven by a third-person actor pronoun.
    if (len(words) >= _NARRATION_MIN_WORDS
            and any(w in _THIRD_PERSON_ACTORS for w in lower_words)):
        return True

    return False


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
        used_thought_default = False

        if kind == KIND_PROSE:
            # Prose is Narrator -- except Sunny inner monologue that genuinely
            # reads first-person (italics don't survive EPUB parsing, so this
            # is the only inner-monologue signal left).
            if not (speaker == "Sunny"
                    and not _is_narrator_misattribution("Sunny", text)):
                if speaker != "Narrator":
                    print(f"[llm]   FIX  prose '{speaker}' -> Narrator | {text[:60]!r}")
                speaker = "Narrator"
        elif kind == KIND_THOUGHT:
            # Quote marks are the structural evidence here -- it IS a thought,
            # even when it mentions others in third person. Trust the POV-character
            # pick; only repair impossible labels.
            if speaker not in allowed or speaker == SYSTEM_SPEAKER:
                speaker = "Sunny"
                used_thought_default = True
        elif kind == KIND_SYSTEM:
            # Brackets carry Spell notifications AND telepathic rune messages --
            # keep any valid roster label, default to the Spell only when impossible.
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
            "kind":       kind,
            "emotion":    emotion,
        })
        if used_thought_default:
            lines[-1]["attribution"] = {"method": "fallback", "cue_indices": []}
    return lines


# ── LLM Director ──────────────────────────────────────────────────────────────

class LLMDirector:
    """
    VRAM-safe LLM director. Must be used as a context manager.

    Example:
        with LLMDirector("models/Qwen3-14B-Q4_K_M.gguf", sm) as d:
            d.process_chapter(chapter_id)
        # Model is fully unloaded here.
    """

    def __init__(
        self,
        model_path: "str | Path",
        state_manager: StateManager,
        speakers: "list[str] | None" = None,
        cfg: "dict | None" = None,
    ):
        self.model_path     = Path(model_path)
        self.sm             = state_manager
        self.speakers       = speakers or DEFAULT_SPEAKERS
        self.cfg            = {**_DEFAULT_CFG, **(cfg or {})}
        self._llm           = None
        self._grammar       = None
        self._ordered_grammars = {}
        self._label_count = 0
        self._system_prompt = _build_system_prompt(self.speakers)
        self._allowed       = _allowed_speakers(self.speakers)

    # ── Context manager (Hardware Enforcer) ───────────────────────────────────

    def __enter__(self):
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed.\n"
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"GGUF model not found: {self.model_path}\n"
                "Recommended: hf download Qwen/Qwen3-14B-GGUF "
                "Qwen3-14B-Q4_K_M.gguf --local-dir models"
            )
        print(f"[llm] Loading model: {self.model_path.name}")
        llama_kwargs = dict(
            model_path=str(self.model_path),
            n_gpu_layers=self.cfg["n_gpu_layers"],
            n_ctx=self.cfg["n_ctx"],
            n_batch=self.cfg["n_batch"],
            flash_attn=self.cfg.get("flash_attn", True),
            verbose=self.cfg["verbose"],
        )
        try:
            self._llm = Llama(**llama_kwargs)
        except TypeError:
            # Older wheels without the flash_attn kwarg.
            llama_kwargs.pop("flash_attn", None)
            self._llm = Llama(**llama_kwargs)
        self._grammar = self._build_grammar()
        print("[llm] Model loaded.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._purge_vram()
        return False

    def _purge_vram(self) -> None:
        if self._llm is not None:
            print("[llm] Unloading model from VRAM...")
            del self._llm
            self._llm = None
        self._grammar = None
        gc.collect()
        # llama.cpp owns its allocations. Clear PyTorch only if it already ran here.
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.empty_cache()
            print("[llm] CUDA cache cleared.")
        print("[llm] VRAM released.")

    def _build_grammar(self):
        """GBNF grammar from the label JSON schema. None on failure -> the call
        falls back to response_format json_object (still parsed + validated)."""
        try:
            schema = json.dumps(_label_json_schema(self.speakers))
            return LlamaGrammar.from_json_schema(schema, verbose=False)
        except Exception as e:
            print(f"[llm] WARNING: grammar build failed ({e}); "
                  "falling back to response_format=json_object")
            return None

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_chapter(self, chapter_id: int) -> int:
        """
        Diarize all chunks for a chapter and persist results to the DB.
        Returns total number of lines written.
        Advances chapter status to 'diarized' via StateManager.
        """
        chunks = self.sm.get_chunks_for_chapter(chapter_id)
        if not chunks:
            raise ValueError(f"No chunks found for chapter_id={chapter_id}")

        print(f"[llm] Processing chapter_id={chapter_id} ({len(chunks)} chunks)...")

        all_lines: list[dict] = []
        for chunk in chunks:
            print(f"[llm]   Chunk {chunk['chunk_index'] + 1}/{len(chunks)} "
                  f"({chunk['word_count']} words)...")
            lines = self._process_chunk(chunk["text"], line_offset=len(all_lines), previous=all_lines[-4:])
            all_lines.extend(lines)
            print(f"[llm]   -> {len(lines)} lines")

        self._review_exchanges(all_lines)
        self._apply_explicit_attributions(all_lines)
        for line in all_lines:
            reasons = [line["review_reason"]] if line.get("review_reason") else []
            if "\ufffd" in line["text"]:
                reasons.append("Source contains an unreadable character; check the book or edit the reading.")
            if (line["speaker"] == "Unknown"
                    or (line["kind"] == KIND_THOUGHT and line["speaker"] == "Narrator")
                    or (line["kind"] in (KIND_DIALOGUE, KIND_THOUGHT)
                        and line.get("attribution", {}).get("method") == "fallback")):
                reasons.append("Speaker needs confirmation.")
            if line["kind"] in (KIND_DIALOGUE, KIND_THOUGHT):
                line.setdefault("attribution", {"method": "inferred", "cue_indices": []})
            if reasons:
                line["review_reason"] = " ".join(reasons)
        source_words = re.findall(r"\w+", "\n".join(chunk["text"] for chunk in chunks))
        directed_words = re.findall(r"\w+", "\n".join(line["text"] for line in all_lines))
        if directed_words != source_words:
            raise ValueError("Directed script changed source text or line order; chapter was not saved.")
        self.sm.save_diarized_lines(chapter_id, all_lines)
        print(f"[llm] Chapter {chapter_id} diarized: {len(all_lines)} total lines.")
        return len(all_lines)

    def _apply_explicit_attributions(self, lines):
        """Use explicit book attributions when the sampled speaker disagrees."""
        from casting import SPEAKER_ALIASES
        actors = {s.casefold(): s for s in self._allowed if s not in ("Unknown", "Narrator")}
        for alias, actor in SPEAKER_ALIASES.items():
            if actor in self._allowed:
                actors.setdefault(alias.casefold(), actor)
        names = "|".join(re.escape(k) for k in sorted(actors, key=len, reverse=True))
        verb = r"(?:said|asked|whispered|answered|replied|muttered|shouted)"
        # Restrict the complete clause: mentioning another actor mid-sentence is weak evidence.
        lead = re.compile(rf"(?:^|[.!?]\s+)({names})\s+{verb}(?:\s+\w+ly)?\s*:$", re.I)
        tail = re.compile(rf"^(?:({names})\s+{verb}|{verb}\s+({names}))(?:\s+\w+ly)?\s*[.,!?]", re.I)
        for i, line in enumerate(lines):
            if line["kind"] != KIND_DIALOGUE:
                continue
            votes = {}
            if i and lines[i-1]["kind"] == KIND_PROSE:
                m = lead.search(lines[i-1]["text"].strip())
                if m:
                    votes.setdefault(actors[m[1].casefold()], []).append(i - 1)
            if i+1 < len(lines) and lines[i+1]["kind"] == KIND_PROSE:
                # '...,' said Jet. A separate 'Jet replied:' introduces the NEXT quote.
                following = lines[i+1]["text"].lstrip()
                if line["text"].rstrip().endswith(",") or following[:1].islower():
                    m = tail.match(following)
                    if m:
                        votes.setdefault(actors[(m[1] or m[2]).casefold()], []).append(i + 1)
            if len(votes) == 1:
                (actor, evidence), = votes.items()
                line["speaker"] = actor
                line["attribution"] = {"method": "explicit", "cue_indices": evidence}
            if i >= 2 and line.get("_paragraph") is not None:
                prev, bridge = lines[i-2:i]
                if (prev["kind"] == KIND_DIALOGUE and bridge["kind"] == KIND_PROSE
                        and prev.get("_paragraph") == bridge.get("_paragraph") == line["_paragraph"]):
                    m = tail.fullmatch(bridge["text"].strip())
                    if m:
                        actor = actors[(m[1] or m[2]).casefold()]
                        prev["speaker"] = line["speaker"] = actor
                        prev["attribution"] = line["attribution"] = {
                            "method": "explicit", "cue_indices": [i - 1]}

    def _review_exchanges(self, lines):
        """Revisit an apparent self-reply using the surrounding scene across chunk boundaries."""
        from casting import SPEAKER_ALIASES
        addresses = {name: name for name in self._allowed}
        addresses.update({name: actor for name, actor in SPEAKER_ALIASES.items() if actor in self._allowed})
        address_names = "|".join(re.escape(name) for name in sorted(addresses, key=len, reverse=True))
        vocative = re.compile(r"(?:^|,\s*)(" + address_names + r")\s*[,!?\.]", re.I)
        names = {name.casefold(): value for name, value in addresses.items()}
        reviewed = set()
        for i in range(1, len(lines)):
            question, answer = lines[i - 1:i + 1]
            if (i in reviewed or question["kind"] != KIND_DIALOGUE or answer["kind"] != KIND_DIALOGUE
                    or "?" not in question["text"]):
                continue
            match = vocative.search(answer["text"])
            listener = names[match[1].casefold()] if match else None
            if question["speaker"] != answer["speaker"] and answer["speaker"] != listener:
                continue
            confirmed_listener = listener is not None and listener == question["speaker"]
            # The next spoken response often disambiguates who asked the question.
            targets = [i - 1, i]
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j]["kind"] == KIND_DIALOGUE:
                    targets.append(j)
                    break
            nearby = lines[max(0, i - 6):min(len(lines), targets[-1] + 5)]
            scene_cast = {row["speaker"] for row in nearby if row["kind"] in (KIND_DIALOGUE, KIND_THOUGHT)}
            if listener:
                scene_cast.add(listener)
            context = "\n".join(f"[{row['kind']}] {row['text'][:420]}" for row in nearby)
            prompt = ("Resolve the speakers of this exchange. A form of address names the listener. "
                      f"The voices in this part of the scene are {', '.join(sorted(scene_cast))}. "
                      "Use the action beats and what each character knows. A speaker may continue "
                      "their own question. Read the scene first:\n" + context +
                      "\n\nReturn labels only for these numbered lines:\n" +
                      "\n".join(f"{k} [D] {lines[j]['text']}" for k, j in enumerate(targets)))
            if self.cfg.get("no_think") or (self.cfg.get("no_think") is None and "qwen3" in self.model_path.name.lower()):
                prompt += "\n/no_think"
            try:
                self._label_count = len(targets)
                labels = _parse_labels(self._call_llm(prompt, temperature=0.1), len(targets))
            except (ValueError, KeyError, TypeError):
                continue
            for k, j in enumerate(targets):
                speaker = labels[k][0]
                if speaker in scene_cast and speaker in self._allowed and speaker not in ("Unknown", "Narrator"):
                    lines[j]["speaker"] = speaker
                    lines[j]["attribution"] = {"method": "exchange", "cue_indices": [t for t in targets if t != j]}
            if confirmed_listener and re.search(r"\byou\b", answer["text"], re.I):
                question["speaker"] = listener
                question["attribution"] = {"method": "vocative", "cue_indices": [i]}
                others = scene_cast - {listener, "Unknown", "Narrator"}
                if len(others) == 1 and answer["speaker"] == listener:
                    answer["speaker"] = next(iter(others))
                    answer["attribution"] = {"method": "vocative", "cue_indices": [i - 1]}
                if len(targets) == 3 and re.search(r"\bif you\b", answer["text"], re.I):
                    reply = lines[targets[-1]]
                    if re.match(r"\s*if I\b", reply["text"], re.I):
                        reply["speaker"] = listener
                        reply["attribution"] = {"method": "vocative", "cue_indices": [i]}
            reviewed.update(targets)

    # ── Internal: segment formatting / merging ─────────────────────────────────

    @staticmethod
    def _format_segments(segments: "list[dict]") -> str:
        return "\n".join(
            f"{s['index']} [{_KIND_TAGS[s['kind']]}] {s['text']}" for s in segments
        )

    def _merge_labels(
        self,
        segments: "list[dict]",
        labels: "dict[int, tuple[str, str]]",
        line_offset: int,
    ) -> "list[dict]":
        """Apply structural speaker enforcement and produce final line dicts."""
        return enforce_labels(segments, labels, self._allowed, line_offset)

    def _fallback_lines(self, segments: "list[dict]", line_offset: int) -> "list[dict]":
        """Total-failure fallback: sensible per-kind defaults, all text preserved."""
        defaults = {
            KIND_DIALOGUE: ("Unknown", "neutral"),
            # Narrator, not Sunny: in Rain-arc chapters a Sunny guess would put
            # the wrong character voice on the thought; narrator-read is safe.
            KIND_THOUGHT:  ("Narrator", "neutral"),
            KIND_SYSTEM:   (SYSTEM_SPEAKER, "cold"),
            KIND_PROSE:    ("Narrator", "neutral"),
        }
        return [{
            "line_index": line_offset + i,
            "speaker":    defaults[seg["kind"]][0],
            "text":       seg["text"],
            "kind":       seg["kind"],
            "emotion":    defaults[seg["kind"]][1],
            "attribution": {"method": "fallback", "cue_indices": []},
        } for i, seg in enumerate(segments)]

    # ── Internal: retry loop ───────────────────────────────────────────────────

    def _process_chunk(self, text: str, line_offset: int, previous=None) -> "list[dict]":
        segments = segment_chunk(text, include_paragraph=True)
        lines = self._label_segments(segments, line_offset, previous, recover=True)
        for seg, line in zip(segments, lines, strict=True):
            line["_paragraph"] = (line_offset, seg["paragraph"])
            if seg.get("review_reason"):
                line["review_reason"] = seg["review_reason"]
        return lines

    def _label_segments(self, segments, line_offset, previous, recover):
        if not segments:
            return []

        user_msg = self._format_segments(segments)
        if previous:
            context = "\n".join(f"{line['speaker']}: {line['text'][-180:]}" for line in previous)
            user_msg = ("Previously directed passage, for speaker continuity only:\n" + context +
                        "\n\nLabel only the following numbered segments:\n" + user_msg)
        _no_think = self.cfg.get("no_think")
        if _no_think is None:
            _model_name = self.model_path.name.lower()
            _no_think = "qwen3" in _model_name or "qwen-3" in _model_name
        if _no_think:
            user_msg += "\n/no_think"  # disable hybrid thinking on Qwen3

        last_error: Optional[Exception] = None
        self._label_count = len(segments)
        for attempt in range(self.cfg["max_retries"]):
            temp = (self.cfg["temperature"] if attempt == 0
                    else self.cfg["retry_temp"])
            try:
                raw    = self._call_llm(user_msg, temperature=temp)
                labels = _parse_labels(raw, n_segments=len(segments))
                return self._merge_labels(segments, labels, line_offset)
            except (ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
                last_error = e
                print(f"[llm]   Label parse error (attempt {attempt + 1}): {e}")
                time.sleep(0.5)

        if recover and len(segments) > 1 and not self.cfg.get("allow_unlabelled_fallback"):
            cut = len(segments) // 2
            left = self._label_segments(segments[:cut], line_offset, previous, recover=False)
            right = [dict(seg, index=i) for i, seg in enumerate(segments[cut:])]
            return left + self._label_segments(right, line_offset + cut, left[-4:], recover=False)
        if not self.cfg.get("allow_unlabelled_fallback") and any(seg["kind"] != KIND_PROSE for seg in segments):
            raise ValueError(f"Could not assign every speaker at line {line_offset}: {last_error}. "
                             "Retry direction or import reviewed labels before recording.")
        print(f"[llm] Using structural defaults after invalid labels: {last_error}")
        return self._fallback_lines(segments, line_offset)

    # ── Internal: raw LLM call (injectable for testing) ───────────────────────

    def _call_llm(self, text: str, temperature: float = 0.2) -> str:
        """
        Single LLM inference call. Separated so tests can monkeypatch this
        without loading any model.
        """
        if self._llm is None:
            raise RuntimeError(
                "LLMDirector must be used inside a 'with' block. "
                "Model is not loaded."
            )
        kwargs: dict = {
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": text},
            ],
            "temperature": temperature,
            "top_p":       self.cfg.get("top_p", 0.8),
            "max_tokens":  self.cfg["max_tokens"],
        }
        # Gemma's chat template has no system role. Include instructions in the
        # user turn so the roster and source-preservation rules reach the model.
        if "gemma" in self.model_path.name.casefold():
            kwargs["messages"] = [{"role": "user", "content": self._system_prompt + "\n\n" + text}]
        if self._label_count:
            if self._label_count not in self._ordered_grammars:
                self._ordered_grammars[self._label_count] = LlamaGrammar.from_string(
                    _ordered_grammar(self._label_count, self._allowed), verbose=False)
            kwargs["grammar"] = self._ordered_grammars[self._label_count]
        elif self._grammar is not None:
            kwargs["grammar"] = self._grammar
        else:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._llm.create_chat_completion(**kwargs)
        return response["choices"][0]["message"]["content"]
