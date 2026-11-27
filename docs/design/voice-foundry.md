# Voice Foundry — design spec

**Status:** draft for review · **Date:** 2026-08-27 · **Target:** ch 2060–2882

Raises listening quality across the audiobook: more voices, cleaner reference clips,
and routing that uses segment *kind* rather than speaker name alone.

---

## 1. Why this exists

Chapter 2261–2882 is **22.0% dialogue** against **12.6%** in the corpus the current
design was sized against — roughly 1.7× more dialogue-heavy. Casting and clip quality
pay out proportionally more in the target window than anywhere already rendered.

### Measured ground truth

| Signal | Value |
|---|---|
| Coverage | ch 1591–2882 contiguous. Missing 1–1590 (deliberate), 2883+ (no source file) |
| Projects | 1 = vol8 (252) · 2 = vol9 (422) · 7 = vol10 (462) · 8 = vol11 (164) |
| Status | proj1: 252 `diarized` · proj2: 348 `complete` + 74 `diarized` · proj7+8: 626 `pending` |
| Lines | 33,351 (proj 7/8 have no line rows — created at diarization) |
| Voices | 41 registered, 91 `SPEAKER_ALIASES`, 0 lines fall to `_default` |
| Render cost | vol10+11 = 33,959 lines ≈ **71.7 GPU-hours** at 7.6 s/line |

Vol10+11 alone slightly exceeds the entire existing corpus. Importing it doubles the
audiobook, and 71.7 GPU-hours collides hard with the power constraint — see §7.

---

## 2. Ear-verified constraints

Established by listening tests on 2026-08-27. **These override acoustic measurement.**
Four separate theories built from acoustic proxies were each refuted by ear; a
correlation study across 14 metrics against the user's own voice ranking produced a best
Spearman rho of only −0.567, below the significance bar set before running it.

> **Acoustic metrics do not predict perceived quality in this project. Every clip or
> emotion change ships only after an ear check. Render variants; let the ear decide.**

Specific findings that constrain the work:

1. **The reference clip is the defect — not the emotion vectors.** Cassie renders cleanly
   at full alpha; Sunny is "kinda robotic" and Nephis "really bad" at *every* alpha, using
   the same vectors and sentence.
2. **Do NOT lower `emo_alpha_scale`.** It stays at `1.0`. In a damping sweep
   (mult 1.00 / 0.60 / 0.35) the user chose **full alpha on 5 of 6**. Damping made it worse.
3. **A reference clip must be conversationally plain, not well-acted.** The user rejected
   the current Effie clip because its performance is strong but "not included in normal
   conversation as the pipeline make it to do." Expressive references fight the emotion
   vector and misfit ordinary dialogue. **This is the acceptance standard for WS5.**
4. **`excited` is bad on every voice; `commanding` is bad on every voice except Sunny;
   `sad` and `pleading` are acceptable; `neutral` is best.** If a clip fix does not rescue
   `excited`, that vector — not the clip — is the remaining defect.
5. **Voice quality ranking:** Cassie > Kai > Rain > Narrator > Lord Valor > Sunny >
   (Nephis, Effie, Fleur). Use the top group as the reference standard for re-cuts.

---

## 3. External credits — what each is for

Both were decided earlier and are load-bearing. Neither renders the audiobook: local
IndexTTS2 remains the renderer.

### 3.1 Fish Audio `s2.1-pro` — via Vercel AI Gateway

Available on Vercel AI Gateway: `s2.1-pro` (TTS + voice cloning from a reference
recording), `s2-pro`, `s1` (emotion/tone markers), `transcribe-1`.

**⚠️Free for 30 days, through September 18 — not a $5/mo tier.** An earlier note in this
project described it as a "$5/mo rate-limited free tier"; that was wrong. List price after
the promo is **$15 per million characters** for TTS.

**⚠️Billing trap: use the `-free` suffix variant.** Without it, usage
*"will automatically begin billing when the offer period ends."*

**⚠️Verify the promo year before relying on the deadline** — the changelog states
"through September 18" without a year. Confirm in the AI Gateway console.

**Measured character volumes (from `chunks.text`, not estimated):**

| scope | characters | cost at $15/M |
|---|---|---|
| 41 voice-clone references | ~12,300 | **$0.18** |
| vol10+11 (ch 2261–2882) | 4,203,762 | $63.06 |
| all vol8–11 | 8,871,729 | $133.08 |

**✅DECIDED 2026-08-27 — Fish is the VOICE FOUNDRY, not the renderer.**

> *"i want Fish Audio to just make the reference audio and build a library for the voices
> of that novel we gonna need, and use it as secondary if we wanted — like just having
> the option."*

- **Primary role — build the reference-clip library.** Costs ~$0.18. The free window is
  irrelevant to it; do not let the Sept 18 deadline rush the ear gates.
- **Secondary role — keep rendering available as an OPTION.** Wire the adapter, leave it
  **off by default**. Local IndexTTS2 remains the renderer. Do not migrate the pipeline.

This closes the fork. §2 established the emotion vectors are sound and only the clips are
defective, so switching renderers would discard the tuned asset to fix a part that is not
broken. The option stays reachable if the power constraint ever forces it.

Acceptance bar for foundry use, from constraint §2.3: each generated reference must be
**plain conversational delivery** — neutral prosody, no performance, no strong emotional
colour. A clip that sounds like good acting is a **failed** reference.

**Gate:** ear-check 2–3 clips before generating all 41 — clone-of-a-clone drift is the
risk. If the first three are not clearly better than the originals, stop and reassess.

Acceptance bar, from constraint §2.3: each generated reference must be **plain
conversational delivery** — neutral prosody, no performance, no strong emotional colour.
A clip that sounds like good acting is a **failed** reference.

**Gate:** ear-check 2–3 clips before generating all 41 — clone-of-a-clone drift is the
risk. If the first three are not clearly better than the originals, stop and reassess.

### 3.2 Fable 5 credit (~$4) — gold reference set (validation instrument)

Produces a small, very-high-quality **gold labelled set**: a few chapters diarized to a
standard good enough to serve as ground truth. This is the measuring instrument for
every diarization change.

It is needed now because the emotion-skew fix applied on 2026-08-27 (see §5, WS3) has
**no objective validation** — the old prompt gave each character a "default" emotion and
the diarizer applied it as a blanket label:

| speaker | lines | top emotion | share |
|---|---|---|---|
| Sunny | 2,460 | cold | **79%** |
| Nephis | 445 | commanding | **63%** |
| Effie | 47 | excited | **51%** |

The prompt now describes each character's *range* plus an anti-skew rule. Whether that
actually helps is currently a judgement call. A gold set turns it into a measurement.

**Spend plan:** 3–4 chapters chosen for cast variety and all four segment kinds. Budget
is small — do not spend it labelling bulk chapters; that is Antigravity's job.

**Gold set defines two scores:** speaker accuracy and emotion accuracy, plus a
**per-speaker skew check** — no speaker's most common emotion above ~45% of their lines,
and dialogue overall near 26% neutral (the figure measured on chapters that came out well).

---

## 4. Architecture change: segment `kind`

`segmenter.segment_chunk()` already computes dialogue / thought / system / prose, then
**discards it** — `lines` has no `kind` column. Because `chunks.text` survives and
diarization is label-only, `kind` is **recoverable by deterministic replay** of the
segmenter. No LLM, no re-diarization.

A replay across the corpus aligned **99.8%** (65-line drift). That drift is why WS1
reconciles *per chapter* and flags mismatches rather than assuming alignment.

---

## 5. Workstreams (dependency order)

### WS1 — `kind` backfill via segmenter replay
Add `kind` to `lines`; replay `segment_chunk()` over `chunks.text` per chapter and
reconcile against stored lines.

- Per-chapter alignment check; on mismatch, **flag and skip** — never guess.
- Report total aligned / flagged. Expect ~99.8% aligned.
- **Rollback:** drop the column.

### WS2 — kind-aware routing — ⚠️ORIGINAL RULE REFUTED BY DATA (2026-08-27)

**Do NOT implement "`system` → The Nightmare Spell". It would cause a regression.**

Measured after the WS1 backfill, `kind=system` contains **two unrelated things**:

| labelled | share | what it is |
|---|---|---|
| The Nightmare Spell | 84% (147) | genuine notifications — "You have slain…" |
| Cassie / Sunny / Rain / Nephis | 16% (28) | **telepathic rune conversation between characters** |

The segmenter marks both as `system` because both are `[bracketed]`. The diarizer prompt
*already* handles this correctly — it labels telepathy with the **sender**. A blanket
kind-override would read Cassie's telepathic lines in the Nightmare Spell's voice.

`kind=thought` shows the same pattern: **Sunny 88%, Rain 5.8%, Morgan 2.5%, Narrator only
2.1% (15 lines)**. The diarizer assigns thoughts to real characters 97.9% of the time.

**Conclusion: for routing, the diarizer's speaker label is already better than any
kind-based override, for both kinds.** WS2's original premise does not survive contact
with the data. `kind` remains valuable — just not as a routing override:

1. **QA / audit signal** — flag suspicious kind↔speaker disagreements (a `system` line
   labelled `Narrator`, a `thought` line labelled `Narrator`) for review. These are
   likely mislabels: 15 + 2 lines today.
2. **Fallback defaults** — already used by `llm_director._fallback_lines` when the LLM
   fails completely; `kind` makes those defaults principled rather than guessed.
3. **Narrator/thought split** (brainstorm "Approach ①") — the only routing case with real
   value: a `thought` line labelled `Narrator` should NOT sound identical to prose
   narration. Scope is small today (15 lines) but it is the correct behaviour.

**Revised WS2 scope:** implement (1) as an audit, keep (2), and treat (3) as the single
narrow routing change. Do not override any line the diarizer labelled with a real
character.
- **Rollback:** revert routing; column can stay.

### WS3 — roster fixes + alias-collision audit
- **Audit all 91 `SPEAKER_ALIASES` keys for ordinary words.** Known live bugs:
  `Fallen` → The Nightmare Abomination and `Weaver` → The Nightmare Spell. Both are
  common setting vocabulary; a diarizer emitting either generically routes to the wrong
  voice **silently**. Same class as the confirmed `Instructor Ram` / `Julius` /
  `Teacher Julius` 3-way collision (byte-identical clips, 8.5s/110 Hz).
- Emotion-skew prompt fix — **already applied** to `src/llm_director.py` and
  `docs/external-formatting-prompt.md` (range instead of default, plus anti-skew rule and
  a ~45% per-speaker cap). Currently **uncommitted and unvalidated**; §3.2 validates it.
- ⚠️ The 348 already-rendered chapters carry the old skewed labels. Re-labelling that
  back-catalogue is a **separate, undecided** call.

### WS4 — ~8–12 new minor voices
Major cast of ch 2261–2882 is **already voiced** (top 12 speakers all have clips). Needed,
all minor: Dreamspawn, Azarax, June, Awakened Kim, Puppeteer, Castellan, Aether, Noctis,
Death Singer, Madoc, Lonesome Howl, Saint Dar, Telle.

Ignore as NER noise: Saint, Other, Demon, Nightmare, Oracle, Pill, Sacred, Abundance,
Domain, Curse, Transcendent, Ascended, Supremes, Flaw, Song, Nether, Wolf.

- **A roster name with no clip falls back to the Narrator voice** — worse than routing to
  an NPC archetype, which has its own voice. Only add a name once it has a clip.
- Judgement pass (which candidates truly speak; which are epithets for someone already
  cast) is a ~25-name question — suitable for Gemini/Antigravity, not a 622-chapter read.

### WS5 — re-cut all 41 clips to one standard  ⭐ highest ear-verified value
The user's original instinct, now confirmed: bad-sounding voices have bad reference clips.

Current state: length spread is **6×** (5.4s–33s), sample rates mixed (22.05k / 24k /
44.1k), and there is a confirmed 3-way duplicate. `narrator.wav` (11.42s) backs 27,779
lines — 83% of the audiobook — and `_default` points at it too.

**Priority order by impact:** Sunny (2,460 lines, "robotic", the protagonist) → Nephis
("really bad") → Effie → the rest.

**Candidates already on disk and rendered for comparison** (`Desktop\clip_bakeoff_listen`,
`Desktop\stage2_emotion_listen`):

| voice | stage-1 ear pick | note |
|---|---|---|
| Sunny | `CURRENT` | `Sunny_ref_alt2.wav` very close behind |
| Nephis | `yennefer_01_12s.wav` | pitch spikes high on one word; `_11` / `_08` under test |
| Effie | `Effie_ref_alt2.wav` | current clip too performed for conversation |

**Deliverable: a single coherent voice library for the novel**, built with Fish and owned
by this repo — not an ad-hoc pile of clips from ElevenLabs previews, game rips and
one-off downloads across three Desktop folders, which is the current state.

**Library standard (every clip, no exceptions):**

| property | value |
|---|---|
| delivery | **plain conversational** — no performance, no strong emotion (§2.3) |
| length | one consistent target (~10–12s); today's spread is 6× (5.4s–33s) |
| sample rate | one rate for the whole library |
| channels | mono, single speaker, no music or background |
| location | `src/data/voices/` — **no external paths** |
| naming | lowercase canonical name, matching the DB `speaker` key |

**⛔VERIFIED 2026-08-27 — voice CLONING IS NOT AVAILABLE via Vercel AI Gateway.**

The gateway model record for `fish-audio/s2.1-pro-free` declares:

```json
"type": "speech",
"modalities": { "input": ["text"], "output": ["audio"] },
"pricing":   { "input": "0", "output": "0" }
```

**Input is text-only — the endpoint will not accept a reference recording.** The model
*description* advertises voice cloning (a Fish Audio capability), but `POST
/v4/ai/speech-model` exposes only `text`, `voice`, `outputFormat`, `instructions`,
`speed`, `language`, where `voice` selects a **preset**. Cloning would require Fish
Audio's own API directly — a separate paid service, not this free promo.

All 4 Fish models are in the catalog with `-free` twins (`s1`, `s2-pro`, `s2.1-pro`,
`transcribe-1`), confirmed zero-priced.

**Consequence — the two paths are NOT equally available:**

1. ❌ **Existing characters — cloning their source clip: NOT POSSIBLE here.** This was
   WS5's core mechanism. Re-cutting Nephis/Effie/Fleur by cloning is off the table on
   this path.
2. ✅ **New characters with no source (WS4's ~8–12 minor roles): fully viable.** Mint a
   voice from a Fish preset, then use that output as the IndexTTS2 reference. These roles
   have no source recording to clone anyway, so the limitation costs nothing.

**So Fish's real value here is WS4, not WS5.** WS5 must fall back to re-cutting from
existing source material by hand (trim/normalise to the library standard), or to a
different cloning provider.

**🔒PROTECTED — do NOT re-cut (user instruction 2026-08-27):**
`Cassie` · `Kai` · `Rain` · `Narrator` · `Lord Valor` · `Sunny`

These are the user's top-ranked voices and none needs redoing. Cassie renders cleanly at
full alpha and is the reference standard for what "good" sounds like. **`narrator.wav`
alone backs 27,779 lines (83% of the audiobook) — touching it risks the most and gains
the least.**

`Sunny` is the one conditional case: the user called him "kinda robotic", but his current
clip **beat all five alternates** in the stage-1 bake-off, so no better source exists on
disk. Fish is the only untried path. Treat as **A/B candidate only** — never replace
unless a Fish version wins by ear.

**Re-cut scope is therefore the other ~35 voices**, led by `Nephis` and `Effie` (both
named bad by the user, both with stage-1 winners already chosen) and `Fleur`.

**Gates and cautions:**
- **Ear-check 2–3 clips before generating all 35** — clone-of-a-clone drift is the risk.
- Priority order is by impact: **Nephis → Effie → Fleur → remaining minor voices.**
- Keep every original under `_archive_old/` and back up the DB before re-pointing paths.
- Do not delete a source clip that outperforms its Fish replacement by ear — for some
  voices the current clip may simply win (the user already picked `Sunny CURRENT` over
  five alternates).
- `src/data/voices/nephis.wav` is still the broken 0.5s file. It is **not** registered
  (the DB points at the yennefer clip) — retire it during this pass.

---

## 6. Validation

One chapter containing all four segment kinds, run end to end, before any migration.

| Workstream | Gate |
|---|---|
| WS1 | ≥99% per-chapter alignment; all mismatches flagged, none silently guessed |
| WS2 | system + thought lines audibly route to the right voice |
| WS3 | gold-set speaker + emotion accuracy; no speaker's top emotion >45% |
| WS4 | every new roster name resolves to its own clip, not the Narrator |
| WS5 | **ear check** — 2–3 clips before the full 41 |

Existing Python tests must stay green (`test_llm_director.py` 40/40 as of this date).

---

## 7. Sequencing — open decision

**None of this produces audio.** 73 diarized chapters sit unrendered and 626 are
`pending`. Rendering vol10+11 locally is ~71.7 GPU-hours, which conflicts directly with
the power constraint (short attended runs only; rely on per-line TTS resume).

The genuine tension: WS5 improves clip quality, but **every chapter rendered before WS5
lands uses clips the user has already rejected by ear.** Rendering first means
re-rendering later. That is a cost call, not a technical one.

### 7.1 Renderer question — CLOSED

**Local IndexTTS2 stays the renderer** (decided 2026-08-27, see §3.1). Fish rendering is
built as an available option, default off. No pipeline migration.

Consequence for sequencing: the 71.7 GPU-hours stand, so the power constraint still
binds, and the render-before-or-after-WS5 tension above is still a live cost call.

Out of scope: **prose flatness** (72% of lines, 93% neutral labels + `narrator_emo_scale`
0.3 damping) — a diarization-quality problem, deferred to a separate "Diarization v3" spec.

---

## 8. Rollback

Per workstream, in reverse order: WS5 restore prior clips from `_archive_old` + DB paths ·
WS4 remove roster names · WS3 `git checkout` the two prompt files · WS2 revert routing ·
WS1 drop the column. Safety points: `git commit 40f5904` (pre-Antigravity),
`src/data/pipeline.db.bak-before-vol10-11`.
