"""
Module 3: LLM Director (Diarization)
======================================
Reads text chunks from the DB, calls a local LLM to produce a structured
JSON script (speaker + emotion per line), and writes results back to the DB.

RECOMMENDED MODEL: Qwen2.5-14B-Instruct Q4_K_M (3-part split, ~9 GB VRAM)
  Download: huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
  Files:    qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf  (~3.99 GB)
            qwen2.5-14b-instruct-q4_k_m-00002-of-00003.gguf  (~3.99 GB)
            qwen2.5-14b-instruct-q4_k_m-00003-of-00003.gguf  (~1.01 GB)
  Pass the -00001-of-00003 file as model_path; llama-cpp finds the rest automatically.
  Fits RTX 4070 (12 GB) with ~2 GB headroom at n_ctx=8192.
  Since LLM and TTS never load simultaneously, Fish Speech 5 GB + 14B 9 GB is fine.

  FALLBACK (lower quality): Qwen2.5-7B-Instruct Q4_K_M (split, ~4.5 GB VRAM)
  Files: qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf  (~2.7 GB)
         qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf  (~1.8 GB)
  Pass the -00001- file as model_path; llama-cpp finds the rest automatically.

INSTALL llama-cpp-python with CUDA:
  pip install llama-cpp-python --extra-index-url \
    https://abetlen.github.io/llama-cpp-python/whl/cu121

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

import collections
import gc
import json
import re
import time
from pathlib import Path
from typing import Optional

try:
    from llama_cpp import Llama
    _LLAMA_AVAILABLE = True
except ImportError:
    _LLAMA_AVAILABLE = False

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
]

EMOTION_VOCAB = [
    "neutral", "whispers", "angry", "sad", "excited",
    "commanding", "frightened", "confused", "pleading",
    "cold", "laughing", "sarcastic", "desperate",
]

# ── LLM generation config ──────────────────────────────────────────────────────
_DEFAULT_CFG = {
    # n_ctx=8192 verified safe for Qwen2.5-14B Q4_K_M on RTX 4070 (12 GB):
    #   model weights ~8.5 GB + KV cache ~1.25 GB = ~9.75 GB total < 12 GB.
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "verbose":      False,
    "temperature":  0.01,   # near-deterministic → consistent attribution across retries
    "max_tokens":   6144,
    "retry_temp":   0.2,    # low retry temperature — avoid hallucination on second attempt
    "max_retries":  3,
    # Minimum fraction of source CONTENT words (len>=4) that must survive into the
    # diarized output. Below this, the LLM silently dropped sentences → retry, then
    # fall back to a verbatim Narrator line. 0.96 cleanly separates real loss
    # (measured 49–94%) from normal normalisation noise (98.5–100%).
    "min_word_coverage": 0.96,
}

# ── System prompt ──────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a precise script director converting "Shadow Slave" prose into a multi-voice audiobook script.

== SPEAKER ROSTER ==
{speakers}
  > Narrator    -- ALL prose, scene description, action, and speech attribution ("he said", "she replied", etc.)
  > [Character] -- ONLY that character's exact spoken words (dialogue)
  > Unknown     -- Dialogue whose speaker cannot be identified from context

== VALID EMOTIONS ==
{emotions}

== MANDATORY RULES ==
R1  ZERO WORDS LOST -- Every single word from the input must appear verbatim in the output.
     Never paraphrase, condense, skip, or alter any text. This rule overrides everything else.

R2  STRICT DIALOGUE / NARRATION SPLIT -- Always produce separate entries:
     > Narrator entry  -- all prose surrounding dialogue including "he said / she replied"
     > Character entry -- only the spoken words (stripped of opening/closing quote marks)

R2a THE QUOTES RULE -- A character speaks ONLY if their exact words are wrapped in
     quotation marks (" " or ' ') in the source text, OR qualify as inner monologue
     under R8 (italic-marked direct thoughts). Otherwise: Narrator.
       OK  "What does it mean?" he asked.  ->  character speaks, then Narrator says "he asked."
       OK  *How did it come to this?*      ->  Sunny's inner monologue -> see R8.
       NO  Sunny wondered what it meant.   ->  Narrator. Sunny is NOT the speaker here.
       NO  He thought: maybe this was it.  ->  Narrator. Unquoted, non-italic thought = Narrator.

R2b THE NARRATOR RULE -- These ALWAYS belong to Narrator, no matter which character is named:
     > Character actions and movements  (e.g. "Sunny walked forward")
     > Character inner thoughts NOT inside quote marks AND NOT italicized (see R8 for italic thoughts)
     > Environmental and scene description
     > Speech attribution phrases  ("he said", "she replied", "Sunny murmured")
     > Any sentence whose grammatical subject is a character name but contains no quoted speech
     !! THE SUBJECT OF A SENTENCE IS NOT THE SPEAKER. Being named does not mean speaking. !!

     SUNNY TRAP -- The protagonist Sunny appears in almost every sentence.
     His name or pronoun (he/him/his) being the grammatical subject does NOT make him the speaker.
     The ONLY valid Sunny entries are:
       a) His exact spoken words inside quotation marks  (R2a)
       b) His direct inner thoughts under Rule R8 (italic or "he thought/wondered" attribution)
     Everything else -- walking, looking, thinking-in-prose, feeling, acting -- is NARRATOR.

R3  STRIP OUTER QUOTES -- Remove open/close quote marks from the very start and end of dialogue
     entries only. Internal apostrophes and contractions ('t, 've, 'm) are kept as-is.

R4  SEQUENTIAL LINE INDEX -- line_index starts at 0, increments by exactly 1 per entry, no gaps.

R5  VALID SPEAKER -- speaker must be exactly one name from the roster. No new names.

R6  VALID EMOTION -- emotion must be exactly one value from the valid emotions list.

R7  UNKNOWN FALLBACK -- If you cannot identify the speaker from context, use Unknown.
     NEVER invent or guess character names that are not in the speaker roster above.
     ANY minor character, guard, servant, stranger, crowd member, or unnamed NPC → Unknown.
     A character's name appearing in narration nearby does NOT put them on the roster.

R8  INNER MONOLOGUE -- This novel is written in close third-person. The protagonist (Sunny /
     Sunless) frequently thinks to himself. These thoughts MUST be assigned to Sunny, NOT
     the Narrator. Two signals identify inner monologue:

     Signal A -- Italic markers: text wrapped in *asterisks* or _underscores_ that reads as
     a direct thought. Strip the * or _ from the output text exactly as R3 strips quotes.
       *How did it come to this?*  ->  speaker: "Sunny", text: "How did it come to this?"

     Signal B -- Contextual mental voice: a rhetorical or first-person-feeling thought
     immediately followed by an attribution like "he thought", "he wondered", "he realised".
       How did it come to this? he wondered.  ->  split: Sunny says the thought,
                                                   Narrator says "he wondered."

     BOUNDARY CHECK -- Not all italics are inner monologue. Stay with Narrator if:
     > Italics emphasize a single word inside a descriptive sentence ("It was *enormous*.")
     > Italics mark a title, term, foreign word, or sound effect (*crack*, *Shadow Slave*)
     > The italic passage describes what Sunny observes, not what he thinks
     Rule of thumb: if the italicized text makes grammatical sense as "I [thought this]",
     assign to Sunny. If it would sound wrong spoken aloud in first person, stay Narrator.

     Emotion for inner monologue: follow the CHARACTER EMOTION GUIDE for Sunny.
     Default: cold. Use confused for questions, desperate for crisis moments.

== CHARACTER EMOTION GUIDE ==
  Narrator : neutral (default) / frightened / desperate (horror, battle, chase scenes)
             excited (revelations, action beats) / angry (conflict narration)
  Sunny    : cold (DEFAULT -- use this unless clearly otherwise) / sarcastic / confused
             -- stoic, rarely openly emotional; neutral only when cold doesn't fit
  Nephis   : commanding (DEFAULT) / cold / neutral  -- always composed, measured
  Cassie   : sad / pleading / neutral  -- gentle and soft-spoken
  Effie    : excited (DEFAULT) / neutral  -- energetic, enthusiastic
  Kai      : neutral / commanding  -- calm, professional

== EXAMPLES ==
Example 1 -- basic attribution split:
Input: Sunny stared at the runes, his expression unreadable. "What does it mean?" he asked quietly. Nephis turned to face him. "Power," she said. "Limitless power."
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"Sunny stared at the runes, his expression unreadable.","emotion":"neutral"}},
  {{"line_index":1,"speaker":"Sunny","text":"What does it mean?","emotion":"confused"}},
  {{"line_index":2,"speaker":"Narrator","text":"he asked quietly. Nephis turned to face him.","emotion":"neutral"}},
  {{"line_index":3,"speaker":"Nephis","text":"Power,","emotion":"cold"}},
  {{"line_index":4,"speaker":"Narrator","text":"she said.","emotion":"neutral"}},
  {{"line_index":5,"speaker":"Nephis","text":"Limitless power.","emotion":"cold"}}
]}}

Example 2 -- action beat between two dialogue fragments of the same speaker:
Input: "Wait," Sunny said, raising his hand. He studied her face carefully. "Let me explain."
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Sunny","text":"Wait,","emotion":"cold"}},
  {{"line_index":1,"speaker":"Narrator","text":"Sunny said, raising his hand. He studied her face carefully.","emotion":"neutral"}},
  {{"line_index":2,"speaker":"Sunny","text":"Let me explain.","emotion":"cold"}}
]}}

Example 3 -- prose misattribution trap (most common mistake -- read carefully):
Input: Sunny looked at the sky and wondered what awaited him in the depths. His shadow stirred.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"Sunny looked at the sky and wondered what awaited him in the depths. His shadow stirred.","emotion":"neutral"}}
]}}
NOTE: Sunny is the grammatical subject, NOT the speaker. No quotation marks = Narrator only.
WRONG would be: {{"speaker":"Sunny"}} -- this is the exact hallucination to avoid.

Example 4 -- unquoted, non-italic prose (always Narrator -- no R8 signal present):
Input: He thought about it for a long moment. Was this really the end? He wasn't sure.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"He thought about it for a long moment. Was this really the end? He wasn't sure.","emotion":"neutral"}}
]}}
NOTE: No italic markers, no attribution like "he wondered" -- plain prose stays Narrator.

Example 5 -- italic inner monologue -- Sunny (R8 Signal A):
Input: *How did it come to this?* he thought, staring at the ruins of what had once been his home.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Sunny","text":"How did it come to this?","emotion":"confused"}},
  {{"line_index":1,"speaker":"Narrator","text":"he thought, staring at the ruins of what had once been his home.","emotion":"neutral"}}
]}}
NOTE: Strip the * markers. Assign to Sunny because it is a direct thought, not description.

Example 6 -- contextual mental voice -- Sunny (R8 Signal B):
Input: Was this truly what it meant to be free? he wondered. Somehow, it felt like anything but.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Sunny","text":"Was this truly what it meant to be free?","emotion":"confused"}},
  {{"line_index":1,"speaker":"Narrator","text":"he wondered. Somehow, it felt like anything but.","emotion":"neutral"}}
]}}
NOTE: The rhetorical question + "he wondered" attribution = R8 Signal B. Split at the attribution.

Example 7 -- italic emphasis inside description (NOT inner monologue, stays Narrator):
Input: The creature was *impossibly* fast, a blur of shadow and malice that left no time to think.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"The creature was impossibly fast, a blur of shadow and malice that left no time to think.","emotion":"frightened"}}
]}}
NOTE: "impossibly" is emphasis on a single descriptive word, not a thought. Strip * and stay Narrator.

Example 8 -- attribution tail after closing quote (split at the quote boundary):
Input: "No, no... you are right. Please enjoy your breakfast." With that, he bowed slightly and took a step back.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Unknown","text":"No, no... you are right. Please enjoy your breakfast.","emotion":"neutral"}},
  {{"line_index":1,"speaker":"Narrator","text":"With that, he bowed slightly and took a step back.","emotion":"neutral"}}
]}}
NOTE: Everything after the closing quote is prose attribution -- always a separate Narrator entry.
WRONG would be: {{"speaker":"Unknown","text":"No, no... you are right. Please enjoy your breakfast. With that, he bowed slightly and took a step back."}}

Example 9 -- Sunny's action paragraph (the most common mistake -- ALWAYS Narrator):
Input: After a while, he sighed and opened his eyes. Sunny looked around, taking in the familiar surroundings of his home. His shadow stirred at the edges of the room.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"After a while, he sighed and opened his eyes. Sunny looked around, taking in the familiar surroundings of his home. His shadow stirred at the edges of the room.","emotion":"neutral"}}
]}}
NOTE: No quotes, no italic inner thought, no "he thought/wondered" -- pure action prose. Narrator only.
WRONG would be: {{"speaker":"Sunny","text":"After a while, he sighed..."}} -- Sunny is NOT speaking here.

Example 10 -- crowd / unnamed NPCs (ALWAYS Unknown when speaker not in roster):
Input: The guards exchanged uneasy glances. "Who goes there?" one of them demanded sharply. "State your business," said the other, stepping forward.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"The guards exchanged uneasy glances.","emotion":"neutral"}},
  {{"line_index":1,"speaker":"Unknown","text":"Who goes there?","emotion":"commanding"}},
  {{"line_index":2,"speaker":"Narrator","text":"one of them demanded sharply.","emotion":"neutral"}},
  {{"line_index":3,"speaker":"Unknown","text":"State your business,","emotion":"commanding"}},
  {{"line_index":4,"speaker":"Narrator","text":"said the other, stepping forward.","emotion":"neutral"}}
]}}
NOTE: "one of them" and "the other" are NOT in the speaker roster → Unknown every time.
NEVER invent a name. NEVER use a named character just because they are present in the scene.

Example 11 -- stranger / minor NPC whose name is not in the roster:
Input: "Your name?" Sunny asked. The man straightened his coat. "Riven. You can call me Riven," he answered.
Output:
{{"lines":[
  {{"line_index":0,"speaker":"Sunny","text":"Your name?","emotion":"cold"}},
  {{"line_index":1,"speaker":"Narrator","text":"Sunny asked. The man straightened his coat.","emotion":"neutral"}},
  {{"line_index":2,"speaker":"Unknown","text":"Riven. You can call me Riven,","emotion":"neutral"}},
  {{"line_index":3,"speaker":"Narrator","text":"he answered.","emotion":"neutral"}}
]}}
NOTE: "Riven" is NOT in the speaker roster → Unknown. Do not add new speakers to the roster.
If a character appears only briefly, always default to Unknown rather than guessing.

Example 12 -- System / Nightmare Spell notification (bracket content is spoken, NOT stage direction):
Input: [Notification: A new Shadow has awakened within you. Embrace the darkness.]
Output:
{{"lines":[
  {{"line_index":0,"speaker":"The Nightmare Spell","text":"[Notification: A new Shadow has awakened within you. Embrace the darkness.]","emotion":"cold"}}
]}}
NOTE: Square bracket notifications from the System are spoken by "The Nightmare Spell" -- do NOT assign to Narrator.
Keep the brackets in the text exactly as they appear in the source.

== OUTPUT FORMAT ==
Respond with ONLY the JSON object below -- no markdown fences, no preamble, no trailing text:
{{"lines":[
  {{"line_index":0,"speaker":"Narrator","text":"...","emotion":"neutral"}}
]}}"""


def _build_system_prompt(speakers: list[str]) -> str:
    speaker_str = "\n  ".join(["Narrator"] + speakers + ["Unknown"])
    emotion_str = ", ".join(EMOTION_VOCAB)
    return _SYSTEM_PROMPT.format(speakers=speaker_str, emotions=emotion_str)


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


# Strips JSON/dict fragments the LLM sometimes embeds in text values, e.g.:
#   "What is that?','emotion\":\"neutral"  ->  "What is that?"
_JSON_LEAK_RE = re.compile(
    r"""[',"\s]+['"]?(?:emotion|speaker|line_index)['"]?\s*[':=]+.*$""",
    re.IGNORECASE | re.DOTALL,
)


def _sanitize_text(text: str) -> str:
    return _JSON_LEAK_RE.sub("", text).strip().strip("'\"").strip()


# First-/second-person markers that signal genuine spoken (or inner-monologue)
# dialogue. If any appear, the line is real speech and must NOT be reclassified.
_DIALOGUE_PERSON_MARKERS = frozenset({
    "i", "i'm", "i'll", "i've", "i'd", "me", "my", "mine", "myself",
    "we", "we're", "we'll", "we've", "us", "our", "ours", "ourselves",
    "you", "you're", "you'll", "you've", "your", "yours", "yourself",
    "yourselves", "let's",
})

# Third-person actor pronouns. Their presence (without any first/second-person
# marker) in a sentence of real length is a strong narration signal.
_THIRD_PERSON_ACTORS = frozenset({
    "he", "she", "they", "him", "her", "them", "his", "their", "its",
})

# Min word count before a bare third-person pronoun counts as narration.
# Guards short third-person dialogue like "He is here." from being nuked.
_NARRATION_MIN_WORDS = 6


def _is_narrator_misattribution(speaker: str, text: str) -> bool:
    """
    Safety net for the most common LLM mistake: assigning prose that *describes*
    a character (their actions, the scene around them) as that character's
    spoken dialogue. The LLM strips quotes from real dialogue (R3), so by the
    time a line reaches here we cannot rely on quotation marks — we instead read
    the grammatical person of the sentence.

    A line is flagged as misattributed narration when, for a NAMED speaker:
      1. The first word is the speaker's name / possessive   ("Sunny walked...")
      2. The first word is a third-person pronoun             ("He sighed...")
      3. The speaker is referred to by their own name in third person, with no
         first/second-person speech marker  ("...Sunny yawned, stretching.")
      4. It is a sentence of real length driven by a third-person actor pronoun
         and contains no first/second-person speech marker
         ("After a while, he sighed and opened his eyes.")

    Lines containing I/you/my/we (genuine speech or inner monologue) are always
    left untouched, even when they also mention the speaker by name
    ("My name is Nephis." stays Nephis).
    """
    if not text or not speaker or speaker in ("Narrator", "Unknown"):
        return False

    words = text.split()
    if not words:
        return False

    speaker_lower = speaker.lower()
    first_word = words[0].rstrip(",.!?:;").lower()

    # Rule 1 — first word is the speaker's name / possessive.
    if first_word in (speaker_lower, speaker_lower + "'s"):
        return True

    # Rule 2 — first word is a third-person pronoun.
    if first_word in _THIRD_PERSON_ACTORS:
        return True

    # Tokenise once, stripping surrounding punctuation and quote glyphs.
    lower_words = [w.strip(",.!?:;\"'“”‘’()").lower() for w in words]

    # Genuine first/second-person speech (or inner monologue) — never reclassify.
    if any(w in _DIALOGUE_PERSON_MARKERS for w in lower_words):
        return False

    # Rule 3 — the speaker narrated by their own name in third person.
    if speaker_lower in lower_words:
        return True

    # Rule 4 — a real-length sentence driven by a third-person actor pronoun.
    if (len(words) >= _NARRATION_MIN_WORDS
            and any(w in _THIRD_PERSON_ACTORS for w in lower_words)):
        return True

    return False


_CONTENT_WORD_RE = re.compile(r"[a-z0-9']+")


def _content_word_coverage(src: str, out: str) -> float:
    """
    Fraction of source 'content words' (length >= 4) that survive into the
    diarized output. Short tokens (articles, numbers, contractions) are excluded
    because text normalisation legitimately alters them (e.g. "26" <-> "twenty-six"),
    whereas dropped sentences remove real content words. Returns 1.0 when the
    source has no content words. Used to catch silent LLM omission.
    """
    def counts(text: str) -> "collections.Counter":
        return collections.Counter(
            w for w in _CONTENT_WORD_RE.findall(text.lower()) if len(w) >= 4
        )

    src_counts = counts(src)
    total = sum(src_counts.values())
    if total == 0:
        return 1.0
    missing = sum((src_counts - counts(out)).values())
    return 1.0 - missing / total


def _parse_lines(response_text: str, line_offset: int = 0) -> list[dict]:
    """
    Parse LLM response into a list of validated line dicts.
    Re-indexes line_index starting from line_offset.
    Skips entries with empty text. Falls back invalid emotions to 'neutral'.
    Raises ValueError on unrecoverable parse failure.
    """
    raw  = _extract_json_block(response_text)
    data = json.loads(raw)

    if "lines" not in data or not isinstance(data["lines"], list):
        raise ValueError(
            f"Response missing 'lines' array. Got keys: {list(data.keys())}"
        )

    lines: list[dict] = []
    for item in data["lines"]:
        text = _sanitize_text(str(item.get("text", "")))
        if not text:
            continue
        emotion = str(item.get("emotion", "neutral"))
        if emotion not in EMOTION_VOCAB:
            emotion = "neutral"
        speaker = str(item.get("speaker", "Narrator"))

        # Catch character-as-narrator misattributions before they reach TTS
        if _is_narrator_misattribution(speaker, text):
            print(f"[llm]   FIX  misattribution: '{speaker}' -> Narrator | {text[:60]!r}")
            speaker = "Narrator"
            emotion = "neutral"

        lines.append({
            "line_index": len(lines) + line_offset,
            "speaker":    speaker,
            "text":       text,
            "emotion":    emotion,
        })
    return lines


# ── LLM Director ──────────────────────────────────────────────────────────────

class LLMDirector:
    """
    VRAM-safe LLM director. Must be used as a context manager.

    Example:
        with LLMDirector("/models/qwen2.5-7b-instruct-q4_k_m.gguf", sm) as d:
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
        self._system_prompt = _build_system_prompt(self.speakers)

    # ── Context manager (Hardware Enforcer) ───────────────────────────────────

    def __enter__(self):
        if not _LLAMA_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python is not installed.\n"
                "Run: pip install llama-cpp-python --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu121"
            )
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"GGUF model not found: {self.model_path}\n"
                "Recommended: huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF\n"
                "  → qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf  (~9 GB, 3-part split)"
            )
        print(f"[llm] Loading model: {self.model_path.name}")
        self._llm = Llama(
            model_path=str(self.model_path),
            n_gpu_layers=self.cfg["n_gpu_layers"],
            n_ctx=self.cfg["n_ctx"],
            n_batch=self.cfg["n_batch"],
            verbose=self.cfg["verbose"],
        )
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
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            print("[llm] CUDA cache cleared.")
        except ImportError:
            pass
        print("[llm] VRAM released.")

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
            lines = self._process_chunk(chunk["text"], line_offset=len(all_lines))
            all_lines.extend(lines)
            print(f"[llm]   -> {len(lines)} lines extracted")

        self.sm.save_diarized_lines(chapter_id, all_lines)
        print(f"[llm] Chapter {chapter_id} diarized: {len(all_lines)} total lines.")
        return len(all_lines)

    # ── Internal: retry loop ───────────────────────────────────────────────────

    def _process_chunk(self, text: str, line_offset: int) -> list[dict]:
        """
        Call the LLM with retry. On total failure, emit the entire chunk
        as a single Narrator line so no text is lost.
        """
        last_error: Optional[Exception] = None
        for attempt in range(self.cfg["max_retries"]):
            temp = (self.cfg["temperature"] if attempt == 0
                    else self.cfg["retry_temp"])
            try:
                raw   = self._call_llm(text, temperature=temp)
                lines = _parse_lines(raw, line_offset=line_offset)

                # Guard against silent omission: the LLM sometimes drops whole
                # sentences despite rule R1. Verify content words survived before
                # accepting the result; otherwise retry (then fall back below).
                coverage = _content_word_coverage(
                    text, " ".join(ln["text"] for ln in lines))
                if coverage < self.cfg["min_word_coverage"]:
                    raise ValueError(
                        f"word loss: only {coverage:.0%} of source content words "
                        f"preserved (min {self.cfg['min_word_coverage']:.0%})")
                return lines
            except (ValueError, json.JSONDecodeError, KeyError) as e:
                last_error = e
                print(f"[llm]   Parse/coverage error (attempt {attempt + 1}): {e}")
                time.sleep(0.5)

        print(f"[llm]   WARNING: all retries failed ({last_error}). "
              f"Falling back to single Narrator line (preserves all text).")
        return [{
            "line_index": line_offset,
            "speaker":    "Narrator",
            "text":       text,
            "emotion":    "neutral",
        }]

    # ── Internal: raw LLM call (injectable for testing) ───────────────────────

    def _call_llm(self, text: str, temperature: float = 0.1) -> str:
        """
        Single LLM inference call. Separated so tests can monkeypatch this
        without loading any model.
        """
        if self._llm is None:
            raise RuntimeError(
                "LLMDirector must be used inside a 'with' block. "
                "Model is not loaded."
            )
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": text},
            ],
            temperature=temperature,
            max_tokens=self.cfg["max_tokens"],
            response_format={"type": "json_object"},
        )
        return response["choices"][0]["message"]["content"]
