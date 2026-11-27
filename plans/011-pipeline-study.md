# 011 · Pipeline study, fixes and additions (2026-11-25)

Owner's request: "do a study on how the current pipeline works and fix it and add what's needed".
Every finding below was measured on this machine and this database; each fix has tests.
Nothing here is committed yet.

## How the pipeline works now

1. **Book → database.** `epub_parser` splits the EPUB into chapters and chunks; `StateManager`
   (SQLite) holds all state. 1,304 chapters: 352 complete, 326 labelled, 626 waiting for labels
   (volumes 10–11).
2. **Labels.** `segmenter` cuts chunks into lines (prose / dialogue / thought / system); speaker
   and emotion come from the director (local Qwen3-14B) or imported labels (Gemini, Claude).
3. **Score.** `performance_score.compile_score` turns each line into an immutable cue: actor via
   `casting.choose_voice` (aliases now chain, e.g. King Anvil → Anvil → Lord Valor), spoken text
   (pronunciations, typography), reference clip + hash, parts of ≤ 350 characters, a take key.
4. **Recording.** `RecordingRoom` routes cues by the cast profile (`profiles/full-cast.json`):
   OmniVoice for the narrator, Sunny and Anvil; Fish S2 Pro for everyone else. One model is in
   VRAM at a time; each engine records its whole share of a chapter in one pass. Takes are cached
   (2 GB shelf), read back with Whisper, retaken once if the words don't match.
   - OmniVoice: worker process, batches of 4, references ≤ 20 s, exact transcripts.
   - Fish S2 Pro: long-lived `audiocpp_server` (~30 s load, then ~2 s per line), references
     ≤ 18 s, voted delivery cues (`profiles/fish-direction.json`), new seed per retake.
5. **Assembly.** `cast_mix` levels each actor to −20 LUFS → **new:** every take gets the same edge
   padding → **new:** pauses follow the book's paragraphs → FFmpeg concat → 320 kb/s MP3 →
   **new:** chapter tags. `performance.json` keeps exact line timings for the UI.
6. **Control.** `PipelineOrchestrator` batches label → VRAM barrier → record → assemble, resumes
   by status after power cuts; FastAPI + SSE drive the Next.js UI.

## What was measured

| Area | Finding |
|---|---|
| Pacing | OmniVoice opens takes with ~200 ms of silence (median; up to 660 ms) and Fish with none. The same narrator→character transition therefore lasted ~790 ms before an OmniVoice line and ~590 ms before a Fish line. |
| Paragraphs | Lines don't store paragraph positions; 41 of chapter 1994's 60 lines start a paragraph, yet every gap was a fixed 200/380 ms. |
| Fish references | A 30 s clip (Jest) needs a 5.8 GB codec graph → out of memory; 21.6 s fits. |
| OmniVoice references | OmniVoice warns that clips over 20 s degrade cloning; 7 registered clips are 21.6–33 s (Morgan, Seishan, Jest, Moonveil, Helie, Warden, Abomination). |
| Orphan risk | The Fish server holds ~10 GB VRAM in its own process; nothing ended it if the backend crashed or was closed (the OmniVoice worker does exit on its own). |
| Cache | Fish take keys hashed the provider's source file, so any edit — even a non-audio one — would have re-recorded every Fish line. |
| Listening packs | Raw takes from the two engines differ by up to 6.6 LU and packs played them unlevelled. Checked: the louder take won only 4 of 15 decided comparisons, so the earlier engine vote stands. |
| Masters | New ch 1994: −20.1 LUFS, true peak −1.3 dBTP (healthy). Old ch 0267 (before per-actor levelling): −24.7 LUFS, +0.1 dBTP (clips slightly) — fixed by re-rendering, no code change. |
| Coverage | 0 of 5,572 character lines fall back to the narrator voice; 0 line errors. |
| Whisper on OmniVoice | `instruct="whisper"` has no effect while cloning (voiced fraction 0.78 vs 0.67 plain). Sunny has 3 whispered lines of 2,460 — accepted. |

## Fixed

1. **Engine-dependent pacing** — `speech_audio.tighten_edges` trims each take to 30 ms lead /
   60 ms tail with 5 ms fades; the threshold follows the take's own peak (quiet whispers keep
   their onsets) with a −55 dBFS floor. Applied to copies at assembly: recorded and cached takes
   are untouched.
2. **Paragraph-blind pauses** — `pacing.mark_paragraphs` finds each line in the chapter text
   (letters and digits only, so quotes and dashes don't matter); `NATURAL_PAUSES`: attribution
   tail 200 ms, same paragraph 300, other voice in the paragraph 380, next paragraph 520, next
   paragraph with another voice 620. Narrator paragraph flow stays ≈ 0.6 s, as approved.
   `pacing: "legacy"` restores the old behaviour.
3. **Fish out of memory on long clips** — cached copies cut at the last sentence end ≤ 18 s (word
   end as fallback) with the matching words; registered clips never modified.
4. **OmniVoice degraded cloning** — the same fitting at its own 20 s limit (clips ≤ 20 s are
   unchanged, so no cached take was invalidated).
5. **Orphaned Fish server** — `process_guard.contain` puts it in a Windows kill-on-close job;
   verified by killing the parent process outright.
6. **Fish cache churn** — explicit `RENDER_VERSION` instead of a source-file hash.
7. **Unlevelled listening packs** — every clip levelled to −20 LUFS (static gain, peak ≤ −1 dBFS);
   `--no-loudness-match` to disable.
8. **Retakes that repeat the failed take** — Fish draws a new seed per attempt.
9. **Anvil's titles missing his new voice** — alias chains.

## Added

- **Chapter tags** in every chapter file: "Chapter 1994: Call to Arms", track, "Shadow Slave,
  Volume 9", author, genre — players list chapters properly.
- **Whole-volume audiobook (.m4b)** with chapter markers, from the UI ("Export audiobook" above
  the chapter list) or `python scripts/export_m4b.py --project 2`. Unfinished chapters are listed,
  never silently skipped. Measured: 39 min of chapters → 18 MB in 24 s.
- **Casting rounds** (`scripts/cast_round.py`): renders lines through the production engines;
  builds a blind engine shoot-out and blind-engine recast pages.
- **Voice-design variants** (`design_voices.py` reads `variants` from the briefs).

## Waiting on the owner's ears

- `data/benchmarks/listening-engines-round2/index.html` — OmniVoice vs Fish for Cassie, Kai,
  Effie, Rain, Jet, Mordret, Morgan, Seishan (24 blind comparisons).
- `data/voice-design/round2/nephis-casting.html` — Nephis recast: 8 voices, each by both engines
  as hidden take A/B; private key `nephis-key.json`.
- `data/benchmarks/listening-pacing/index.html` — old vs new pacing on two chapter 1994 excerpts.

## Recommended next (not done)

- Label volumes 10–11 (626 chapters) — the main production blocker.
- Apply the round-2 votes: per-character routes in `full-cast.json`; register the Nephis pick
  additively.
- Chapters are 320 kb/s MP3 of 24 kHz speech (~2.3 MB/min); 128 kb/s would cut size ~60% with no
  audible loss. Unchanged pending the owner's OK.
- Spoken chapter headings ("Chapter 1994: Call to Arms") at the start of each file, as commercial
  audiobooks do — needs a narrator take per chapter and touches score, assembler and UI.
- Files over 500 lines, flagged for a split: `api.py`, `llm_director.py`, `state_manager.py`,
  `orchestrator.py`.

## Second pass (same day): naming, casting system, round 3

**Corrections to the first pass.** (1) "0 lines fall back to the narrator" was true of the
fallback rule but misleading: 325 lines labelled "Unknown" map to `_default`, which is the
narrator's clip. (2) The idea of choosing engines automatically by speaker similarity was
tested against the owner's 36 identity votes and agreed on 19 — chance — so engines and voices
stay ear-decided; metrics only screen for defects.

**Engine votes, round 2 (pack 05517a56…):** Rain, Mordret, Kai, Morgan → Fish; Cassie, Seishan,
Effie → OmniVoice (Effie on identity, 2–0); Jet → "neither" twice: recast. Routes applied in
`profiles/full-cast.json`.

**Chapter naming (owner: "names from file don't match the real number and name").** Causes:
masters were named by database id (`ch_0254.mp3` = Chapter 1841); the UI showed EPUB position
(`chapter_index + 1`, so Chapter 1994 appeared as 141); headings came in five shapes
("Chapter: 2232 Cold Front", "Chapter '2362 Hunter and Prey"…); each volume ended with a
contents page numbered after the entry count ("Chapter 422"), already labelled in vols 8–9
and narratable; 49 chapters repeat their heading inside the text. Fixes: `src/chapter_titles.py`
(identity: kind / real number / clean title); new `chapters` columns `chapter_number`,
`display_title`, `kind`, filled automatically (1,292 story chapters numbered, 4 synopsis, 4
contents pages, zero gaps 1591–2882); files now `data/output/Shadow Slave, Volume 9/1994 - Call
to Arms.mp3` with matching tags; contents pages are never rendered or exported; a first line that
only repeats the heading is a pause (no index shift, so prepared labels stay valid); UI shows the
book's numbers and clean titles everywhere, hides contents pages, and takes ranges as real
chapter numbers (`chapter_numbers` in the API). `scripts/rename_chapter_files.py` moved the 352
existing masters (+ timing sidecars) and updated the database — undo log in `data/output/`.
Six June-era `ch_*.mp3` leftovers in `src/data/output` are unreferenced and were left alone.

**Casting system ("make sure the pipeline chooses the best voice for every character").**
discover (`src/cast_discovery.py`: labelled counts + an attribution estimator for unlabelled
volumes — beat-before-quote, exchanges, proper-noun filter; calibrated on vol 9) → brief
(`profiles/voice-briefs.json`, novel evidence + variants) → design (`design_voices.py`) → screen
(`src/voice_screening.py`: script read-back ≥ 85%, pitch fits gender/age, not ≥ 0.85 similar to an
existing cast voice) → audition (`cast_round.py`: real book lines through the production
engines, one combined page, per-character engine) → owner picks → apply (`scripts/cast.py
apply`: registers picks from `editions/` with exact scripts, sets engine routes, logs
`profiles/cast-decisions.json`, refuses protected voices). NPC archetypes can now hold voice
pools ("The Bureaucrat", "The Bureaucrat #2", …) chosen per chapter.

**Round 3:** post-2300 discovery (estimates ≈ ⅓ of true counts): Effie 264, Jet 223, Saint Naeve
176, Asterion 78 (recasts) and unvoiced Azarax 27, Yutra 24, Little Ling 22, Pill 11, Noctis 8,
Tegrot 8, Death Singer 6, Beth 6, Quentin 5, plus the five NPC archetypes — 54 designed
candidates, screened, auditioned on one page.

## Third pass: who speaks, and with what emotion

Owner: "are you sure the Qwen [knows] which one is talking ... and uses the best emotion?" It
did not. Measured on the volume 8-9 labels (made by Claude/Gemini; Qwen scores 53/59 on the
gold set): labels contradicted an explicit "X said" on 13 of 80 lines (16%), and a hand check of
10 action-beat disagreements found 6 real errors, mostly lines given to Sunny. Emotions were
skewed: Nephis "commanding" on 64% of her lines (a Fish cue on 70% of them), Sunny "cold" 70%,
"confused" 30-45% for several characters.

Added a label-checking layer for any labeller (`src/label_audit.py`, `scripts/audit_labels.py`):
explicit contradictions are corrected; action-beat contradictions (minus "looked at"-style
hand-offs) go to Qwen as a two-option question in random order and change only if Qwen sides
with the book. Run: 13 explicit + 146 of 169 beat conflicts -> 159 lines relabelled in 97
chapters (Sunny->Nephis 35, Lord Valor->Jest 17, Sunny->Cassie 11, Cassie->Ki Song 10,
Tamar->Rain 9). Undo log in `data/label-audit/`; DB backed up. 38 already-recorded chapters keep
the old voices on those lines until re-rendered. Emotion: a label covering >40% of a character's
lines (min 20) is treated as that character's normal delivery and fires no Fish cue — in effect
removing Nephis's 64% "commanding" cue. Run `audit_labels.py --adjudicate --projects 7 8` after
volumes 10-11 are labelled.

**Hand check (50 random volume 8-9 dialogue lines):** 28 right, 19 wrong, 3 unclear - about 60%. Most errors follow pronoun attributions ("she said:", "He looked at her"), where labels keep the previous speaker or default to Sunny, often with the wrong gender. The audit above only covers lines with a named cue. Recommendation: re-label volumes 8-9 with the local Qwen director (about 90% on the gold set) plus the audit before re-rendering further.

## Verification

`python -m pytest -q` (304 passing), `cd ui && npm test` (53 passing), `npm run typecheck`,
`npm run build`; chapter 1994 rendered end to end through `scripts/benchmark_chapter.py 407
--reuse-labels` with the default profile.
