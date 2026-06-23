# External Formatting Prompt (round-trip diarization)

Use this to diarize any Shadow Slave chapter/volume **outside** the local LLM — with the
Claude API, another capable model, or by hand — and import the result back into the
pipeline. It is tuned for the **later volumes (vol8 → vol11, chapters ~1591–2882)**, where
the cast is large and characters are constantly referred to by **titles/epithets**.

## How the round-trip works (read first)

The AI does **not** rewrite the chapter. The pipeline splits each chapter into numbered
**segments** deterministically (`src/segmenter.py`), exports them as `ch_XXXX.segments.json`,
and the AI's only job is to attach **one speaker + one emotion to each segment index `i`**.
On import the text is re-derived verbatim from the stored EPUB — external text is never
trusted (`src/diarization_io.py`). Word-loss is impossible; accuracy depends only on the
speaker/emotion labels.

The output contract is enforced on import (`enforce_labels`, shared with the local LLM):
- **speaker** ∈ the roster, the NPC archetypes, `Narrator`, `Unknown`, or `The Nightmare Spell`
- **emotion** ∈ the 13 emotions below
- **exactly one label per segment index**, in order

Anything outside those sets is repaired (bad speaker→`Unknown`, bad emotion→`neutral`), so
staying inside them is what makes a clean import.

## Easiest path: one button in the UI

Open a chapter's Inspector → **External diarization** → paste your Anthropic API
key once (stored in the browser only, never on the server) → click **✨ Diarize
with Claude**. That runs the whole round-trip server-side (export → Claude →
import) and flips the chapter to `diarized`. No files, no terminal. The manual
export/label/import steps below are still there for whole volumes or hand-labelling.

## End-to-end for any volume

1. **Parse the EPUB into the project first** (`POST /api/project`) so the volume's chapters
   + chunks + segments exist. The prompt cannot label a volume that hasn't been segmented.
2. **Export segments** — UI **↓ Export segments** (per-chapter Inspector, visible for every
   status), or:
   ```powershell
   python scripts/diarize_io.py export --project "Shadow Slave" --range <start> <end> --out data/diar_export
   ```
   The CLI also writes `system_prompt.txt` (the canonical machine prompt) next to the files.
3. **Label** — paste the prompt below + the segment lines (`i [KIND] text`) into the AI, or
   run the automated path:
   ```powershell
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   python scripts/diarize_io.py format-cloud --in data/diar_export --model claude-opus-4-8
   ```
   Output: one `ch_XXXX.labels.json` per chapter.
4. **Import** — UI **↑ Import labels**, or
   `python scripts/diarize_io.py import --project "Shadow Slave" --in data/diar_export`.
   Status flips to `diarized`; check the Inspector's Diarization table or the **↓ Diarization**
   download. Re-importing a chapter past `diarized` needs the **force overwrite** toggle
   (clears that chapter's audio).

---

## The prompt (paste verbatim)

```
You label pre-split segments of the "Shadow Slave" web novel for a multi-voice audiobook.
You NEVER output text -- only one speaker and one emotion label per segment.

== SEGMENT KINDS ==
[D] dialogue -- words spoken aloud by a character. Label with the speaker's name.
[T] thought  -- inner monologue of the scene's point-of-view (POV) character.
[P] prose    -- narration, description, actions, attribution tails ("he said"). Label Narrator.
[S] system   -- [bracketed] Nightmare Spell notification. Label The Nightmare Spell.

== SPEAKERS (named roster -- use these EXACT names for named characters) ==
Narrator
Sunny
Nephis
Cassie
Effie
Kai
Morgan
Luster
Jet
Rain
Ray
Aiko
Fleur
Tamar
Mordret
Roan
Kim
Asterion
Julius
Tyris
Revel
Jest
Seishan
Helie
Beastmaster
Anvil
Ki Song
Eurys
Naeve
Bloodwave
Moonveil
Warden
Unknown
The Nightmare Spell

== NPC ARCHETYPES (for UNNAMED / non-roster speakers -- pick the best fit, not Unknown) ==
The Hardened Awakened   : soldiers, hunters, guards, mercenaries, veteran fighters.
The Bureaucrat          : officials, academy instructors, clerks, administrators, hosts.
The Legacy Noble        : clan members & aristocrats (Valor, Song, Ki, the great houses).
The Dream Realm Wanderer : scavengers, Sleepers, slaves, desperate survivors.
The Nightmare Abomination: monsters, demons, the corrupted, hostile entities that speak.
Use an archetype ONLY for a speaker who is not a named roster character. When none clearly
fits an unnamed speaker -> Unknown.

== EMOTIONS ==
neutral, whispers, angry, sad, excited, commanding, frightened, confused, pleading, cold,
laughing, sarcastic, desperate

== EPITHET GLOSSARY (later volumes name characters by TITLE -- map the title to the name) ==
Sunny    : Sunless, Lord of Shadows, the Shadow, Devil of Antarctica, Weaver's Heir,
           the Shopkeeper, Mongrel; (vol10 undercover) Detective Sunless, Sir Sunless.
Nephis   : Changing Star, the Saint of Light, Lady/Saint Nephis.
Cassie   : Song of the Fallen, the Seer, the Blind Girl, Saint Cassia.
Effie    : Athena, Raised by Wolves, (vol10) Detective Athena.
Kai      : Nightingale.            Jet     : Soul Reaper, Boss.
Morgan   : Princess/Saint Morgan.  Mordret : Prince of Nothing.
Anvil    : King of Swords, Lord/King Valor, Anvil of Valor.
Ki Song  : Queen of Beasts, Queen of Song.    Eurys : Eurys of the Nine.
Naeve    : the Nightwalker, Saint Naeve.       Bloodwave : Saint Bloodwave.
Revel    : the Dirge, the Dark Dancer.         Tyris : Sky Tide.   Tamar : Lady Tamar.
Moonveil : Princess Moonveil.                  Warden : Warden of Valor.
The Nightmare Spell : the Weaver, the Spell, the System.
A title resolves to the roster name. Mordret's "Reflections" / "Other Mordret" -> Mordret.
If a title belongs to nobody on the roster, the speaker is an NPC archetype or Unknown --
NEVER invent a new roster name.

== POV / THOUGHT RULES (critical in vol8-11: the story is multi-POV) ==
[T] thought segments belong to the scene's POV character -- the person whose senses and
inner voice the narration is following -- NOT the Narrator and NOT a person they think about.
- Identify the POV from the focal character of the scene. It is OFTEN Sunny, but long
  stretches follow Rain (her own campaign), and chapters/interludes follow others
  (Nephis, Cassie, Effie, or a one-off Awakened). Track POV across scene breaks.
- A [T] thought may mention other people in third person ("She has been gone a month...")
  -- it is still the POV character's thought.
- A [P] prose segment is Narrator. ONE exception: a [P] line that is clearly the POV
  character's direct first-person thought ("Why me?", "I have to run.") may take that
  character. Third-person prose about them ("Sunny walked...", "He sighed...") is Narrator.

== ATTRIBUTION RULES ==
A1 Attribution tails name the speaker. In `1 [D] Wait, / 2 [P] Sunny said`, segment 1 is Sunny.
A2 With no tail, follow conversation flow: two characters in a scene usually alternate turns.
A3 Named roster names are for NAMED roster characters only. Unnamed/non-roster speaker ->
   best-fitting NPC archetype, else Unknown. An introduced-but-unlisted name (e.g. "Riven")
   is NOT a roster member.
A4 [S] system: Nightmare Spell notifications ("You have slain...", "Your shadow grows
   stronger...") -> The Nightmare Spell. Brackets are ALSO used for telepathic rune/Song
   messages between characters -- if the surrounding prose shows a character sending or
   answering ("Cassie's voice sounded in her mind: [...]"), label the SENDER instead.
   A bare stat/item readout the narrator would read ([1591/6000]) -> Narrator.

== EMOTION GUIDE ==
Narrator : neutral default / frightened, desperate in horror or battle / excited at reveals.
Sunny    : cold default / sarcastic / confused -- stoic, rarely openly emotional.
Nephis   : commanding default / cold / neutral -- always composed.
Cassie   : sad / pleading / neutral -- gentle, soft-spoken.   Effie : excited / neutral.
Kai      : neutral / commanding.    Rain : confused / frightened / excited -- expressive.
Mordret  : sarcastic / cold / commanding -- theatrical, mocking.
Anvil    : commanding / cold -- stern, kingly.    Jest : sarcastic / laughing / excited.
Dialogue emotion follows the words AND the manner-cue in the attribution around it:
- A manner-cue in the [P] segment right before/after a [D] line sets that line's tone:
  "whispered/murmured/hushed" -> whispers; "shouted/barked/roared" -> angry or excited;
  "pleaded/begged" -> pleading; "said coldly/hissed" -> cold. The cue usually sits in the
  PREVIOUS or NEXT prose segment, NOT inside the spoken words -- carry it onto the [D] line.
- questions -> confused ONLY when the speaker is genuinely uncertain. A rhetorical, rote, or
  commanding question keeps the speaker's default tone.
- threats -> cold or angry; shouting -> angry or excited; hushed speech -> whispers.

== EXAMPLE 1 (basics: dialogue / thought / system) ==
Input:
0 [P] Sunny stared at the runes, his expression unreadable.
1 [D] What does it mean?
2 [P] he asked quietly. Nephis turned to face him.
3 [D] Power. Limitless power.
4 [S] [You have slain a Great Demon.]
5 [T] So that's what the runes were hiding all along...
Output:
{"labels":[
{"i":0,"speaker":"Narrator","emotion":"neutral"},
{"i":1,"speaker":"Sunny","emotion":"confused"},
{"i":2,"speaker":"Narrator","emotion":"neutral"},
{"i":3,"speaker":"Nephis","emotion":"cold"},
{"i":4,"speaker":"The Nightmare Spell","emotion":"cold"},
{"i":5,"speaker":"Sunny","emotion":"cold"}]}

== EXAMPLE 2 (unnamed -> archetype, never a new name) ==
Input:
0 [P] The guards exchanged uneasy glances.
1 [D] Who goes there?
2 [P] one of them demanded sharply.
3 [D] Your name?
4 [P] Sunny asked. The man straightened his coat.
5 [D] Riven. You can call me Riven.
Output:
{"labels":[
{"i":0,"speaker":"Narrator","emotion":"neutral"},
{"i":1,"speaker":"The Hardened Awakened","emotion":"commanding"},
{"i":2,"speaker":"Narrator","emotion":"neutral"},
{"i":3,"speaker":"Sunny","emotion":"cold"},
{"i":4,"speaker":"Narrator","emotion":"neutral"},
{"i":5,"speaker":"Unknown","emotion":"neutral"}]}
Note: the unnamed guard is a soldier -> The Hardened Awakened. "Riven" introduces himself
but is unlisted and his role is unclear -> Unknown.

== EXAMPLE 3 (manner-cue carries onto the spoken line) ==
Input:
0 [P] Cassie leaned close and whispered into his ear.
1 [D] They are watching us. Say nothing.
2 [P] Sunny gave a slow nod, then asked evenly.
3 [D] How many?
Output:
{"labels":[
{"i":0,"speaker":"Narrator","emotion":"neutral"},
{"i":1,"speaker":"Cassie","emotion":"whispers"},
{"i":2,"speaker":"Narrator","emotion":"neutral"},
{"i":3,"speaker":"Sunny","emotion":"neutral"}]}

== EXAMPLE 4 (epithet -> roster name; unnamed soldier -> archetype) ==
Input:
0 [P] The Changing Star regarded the soldier coldly.
1 [D] Report. How many did we lose?
2 [P] The grizzled veteran lowered his head.
3 [D] Thirty, my Saint. The Hollows broke through the eastern wall.
Output:
{"labels":[
{"i":0,"speaker":"Narrator","emotion":"neutral"},
{"i":1,"speaker":"Nephis","emotion":"commanding"},
{"i":2,"speaker":"Narrator","emotion":"neutral"},
{"i":3,"speaker":"The Hardened Awakened","emotion":"frightened"}]}
Note: "Changing Star" is Nephis (epithet). The unnamed veteran -> The Hardened Awakened.

== EXAMPLE 5 (multi-Sovereign council: keep epithets straight) ==
Input:
0 [P] Anvil's gaze swept the war table. He spoke first, his voice like iron.
1 [D] The Song Domain holds. For now.
2 [P] Across from him, the Queen of Song inclined her head.
3 [D] My daughters will not yield the eastern shore.
4 [P] In the shadows, the Nightwalker watched them both, and finally murmured:
5 [D] You are both being played.
Output:
{"labels":[
{"i":0,"speaker":"Narrator","emotion":"neutral"},
{"i":1,"speaker":"Anvil","emotion":"commanding"},
{"i":2,"speaker":"Narrator","emotion":"neutral"},
{"i":3,"speaker":"Ki Song","emotion":"commanding"},
{"i":4,"speaker":"Narrator","emotion":"neutral"},
{"i":5,"speaker":"Naeve","emotion":"whispers"}]}
Note: "Queen of Song" -> Ki Song; "the Nightwalker" -> Naeve; "murmured" -> whispers.

== OUTPUT ==
Return ONLY this JSON object, exactly one label per input segment, in order:
{"labels":[{"i":0,"speaker":"...","emotion":"..."}]}
```

---

## Voice routing (what the labels become)

Each speaker label resolves to a reference voice in the TTS engine (`SPEAKER_ALIASES` +
the voice map). Notes for the late-volume cast:

- **Resolve to their own voice:** Sunny, Nephis, Cassie, Effie, Kai, Morgan, Jet, Rain, Ray,
  Aiko, Fleur, Mordret, Roan, Kim, Asterion, Luster, Tamar, Revel, Tyris, Julius,
  Beastmaster, **Anvil**(→Lord Valor), **Ki Song**(→Queen Ki Song), **Eurys**, **Naeve**,
  **Bloodwave**, and all 5 archetypes.
- **No clip yet → currently fall back to the Narrator voice:** **Jest, Seishan, Helie,
  Moonveil, Warden.** Label them correctly anyway (the labels are right and future-proof) —
  then register a clip via the UI **Voices** tab / `POST /api/voices` so they get a distinct
  voice. Jest is a frequent vol9 speaker, so it's the highest priority.
- The 5 NPC archetypes each have a distinct registered voice, so routing an unnamed speaker
  to the right archetype is what stops every guard/official/monster from sounding like the
  narrator.

## Quality checklist (the details that matter)

- **Exactly one label per segment, in order.** Import rejects the file if the count ≠ segment
  count, or any index is duplicated/missing. Don't merge, split, skip, or reorder segments.
- **Never touch the text** — labels only. Text is re-derived from the EPUB on import.
- **Resolve epithets** to roster names (glossary). This is the #1 accuracy lever post-vol-8.
- **Unnamed → archetype, not Unknown**, whenever a role clearly fits (soldier/official/
  noble/scavenger/monster). Reserve `Unknown` for genuinely unclassifiable speakers.
- **Track POV** for `[T]` thoughts — it is not always Sunny in vol8-11 (Rain has her own arc).
- **Brackets are overloaded:** Spell notification → `The Nightmare Spell`; telepathy → the
  sender; bare stat readout → `Narrator`.
- **Long chapters / context limits:** a chapter can be hundreds of segments. If pasting into
  a chat UI, split into ranges but keep the original absolute `i` values and concatenate the
  `labels` arrays. The CLI `format-cloud` path handles size automatically — prefer it for
  whole volumes.
- **Verify after import:** status should read `diarized`; spot-check with the Inspector's
  Diarization table or the **↓ Diarization** download before running TTS.

> The roster, archetypes, and emotion vocabulary are generated from `DEFAULT_SPEAKERS`,
> `NPC_ARCHETYPES`, and `EMOTION_VOCAB` in `src/llm_director.py`. If those change,
> regenerate the machine prompt via `src/diarization_io.py::build_system_prompt_text()` (or
> read `system_prompt.txt` from a fresh export) so labels keep matching the importer.
