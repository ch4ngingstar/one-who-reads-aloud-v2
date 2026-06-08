"""
Module 3: LLM Director (Diarization)
======================================
Reads text chunks from the DB, calls a local LLM to produce a structured
JSON script (speaker + emotion per line), and writes results back to the DB.

MODEL: Qwen2.5-7B-Instruct Q4_K_M (GGUF - split across 2 files)
  Download: huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF
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
    "n_ctx":        8192,
    "n_batch":      512,
    "n_gpu_layers": -1,
    "verbose":      False,
    "temperature":  0.05,
    "max_tokens":   6144,
    "retry_temp":   0.3,
    "max_retries":  3,
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


def _is_narrator_misattribution(speaker: str, text: str) -> bool:
    """
    Safety net for the most common LLM mistake: assigning prose that describes
    a character (starting with their own name) as that character's dialogue.

    Example caught:
      speaker="Sunny", text="Sunny walked forward, his eyes fixed on the gate."
      → reclassify to Narrator because spoken lines never start with the speaker's own name.

    Not triggered for inner monologue like "Sunny... that name felt hollow now."
    because those are rare and the LLM handles them better with R8 guidance.
    """
    if not text or not speaker or speaker in ("Narrator", "Unknown"):
        return False
    # "Sunny said..." / "He walked..." assigned to Sunny — third-person prose, not speech
    first_word = text.split()[0].rstrip(",.!?:").lower() if text.split() else ""
    return first_word == speaker.lower()


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
                "Download from: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF"
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
                raw = self._call_llm(text, temperature=temp)
                return _parse_lines(raw, line_offset=line_offset)
            except (ValueError, json.JSONDecodeError, KeyError) as e:
                last_error = e
                print(f"[llm]   Parse error (attempt {attempt + 1}): {e}")
                time.sleep(0.5)

        print(f"[llm]   WARNING: all retries failed ({last_error}). "
              f"Falling back to single Narrator line.")
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
