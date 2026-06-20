# LLM Council Transcript — June 19, 2026

## Original Question

"gave feedback + what do u think is good way to improve the performance"

(The June 15 council's feedback — fix unattended batch reliability, ship an audio demo — has been acted on: reliability fixes landed and the demo is live. This council narrows to the remaining question: how to make the pipeline *faster*.)

## Framed Question

A working local audiobook pipeline for the Shadow Slave web novel (public GitHub repo, MIT). It parses an EPUB, diarizes each chapter via a local 14B Qwen3 GGUF LLM (~9GB VRAM), synthesizes speech with IndexTTS2 zero-shot voice cloning with per-line emotion vectors (~8GB VRAM, in-process), and assembles per-line WAVs into chapter MP3s via FFmpeg.

**Hard constraint:** ~12GB VRAM. The LLM and TTS can never co-reside. The orchestrator runs them strictly sequentially *per chapter*: load LLM → diarize → unload → VRAM barrier (poll nvidia-smi until <1GB) → load IndexTTS2 → synthesize all lines → unload → FFmpeg assemble (CPU).

**Current performance:** TTS is the bottleneck at ~11–17s/line (30–200 lines/chapter); diarization ~45s/chapter; ~655 chapters pending. A prior fix cut num_beams 5→3 (~100s → ~17s/line). fp32 kept. use_deepspeed=False on Windows. User is in Iraq with frequent power cuts → relies on per-line resume and short runs. Reliability work (VRAM timeout, pipeline.log, FFmpeg guard, WAV cleanup) is done; audio demo is live.

**The question:** What's the highest-leverage way to improve performance, and what's being overlooked?

---

## Advisor Responses

### The Contrarian
The num_beams 5→3 fix already happened, so the obvious lever is gone. The fatal assumption: that per-chapter load/unload is "free" relative to TTS. It isn't — loading a 14B GGUF AND IndexTTS2 AND polling nvidia-smi to <1GB happens 655 times. If load+barrier is 60–90s/chapter, that's 16+ hours of pure swap overhead — unmeasured. Measure it before touching anything. Second, fp32: you "kept" it, which sounds like a decision but reads like fear. fp16 is the single biggest available speedup and you're refusing it without stating an observed quality regression. Prove the degradation is audible — if it isn't, you're leaving ~2x on the table out of superstition. Third, the one nobody's saying: stop swapping entirely. Diarize 20 chapters in ONE LLM session, unload once, synthesize 20 in ONE TTS session — same VRAM ceiling, 1/20th the swap tax. The thing being avoided: with frequent power cuts, none of this matters if a 16-hour run dies at hour 14. Throughput isn't the real bottleneck — resumability is. Fix that first.

### The First Principles Thinker
Strip the question down: the goal isn't "make TTS faster," it's "produce 655 listenable chapters on a power-cut-prone 12GB machine in Iraq." Seconds-per-line is the wrong frame. Math: ~17s/line × ~100 lines = ~28min TTS/chapter, ~300+ hours total. The real enemy is the per-chapter load/unload/VRAM-barrier dance paid 655 times, plus power cuts meaning you never get a long clean run anyway. The actual problem is batching and amortization, not per-line speed. Flip the orchestrator: diarize 20–50 chapters in ONE LLM session (model stays hot, no reload, no barrier), unload once, then synthesize all of them in ONE TTS session. Eliminates ~650 model loads and ~650 barriers, zero quality risk, and directly serves the "short runs between blackouts" reality. What's overlooked: you don't need the whole novel generated — who listens to 655 chapters back-to-back? Generate on-demand or N-chapters-ahead of where the listener actually is. The cheapest computation is the one you never run. And question fp32 — A/B three lines.

### The Expansionist
IndexTTS2 synthesizing one line at a time is the single most undervalued opportunity. The model processes 30–200 lines serially at ~15s each, but TTS inference is dominated by fixed per-call overhead and underutilized GPU. Batch the lines — even batch-of-4 on the GPT/semantic stage could 2–3x throughput on the same hardware, for free. Bigger: you load/unload two ~9GB models 655 times — pure thrash. Decouple the stages: diarize ALL 655 chapters in one continuous LLM session, then run TTS for everything in one continuous session, eliminating ~1300 load/unload cycles and the barrier between every chapter. The overlooked upside nobody's pricing in: once diarization is cached as structured data, it's a reusable asset — re-render the entire audiobook with a better TTS model, different voices, or fixed pronunciations WITHOUT re-running the 14B LLM. The diarized JSON is the real product. Build the pipeline around that re-renderable asset and you've turned a one-shot render into a re-renderable library.

### The Outsider
The TTS load/unload cycle is the elephant nobody is naming — you wrote it as a HARD CONSTRAINT and then everyone, including you, stopped questioning it. What does one cold load of IndexTTS2 actually cost in wall-clock seconds? That number is suspiciously absent. If it's 30–60s, you're throwing away 5–10 hours of loading across the backlog — invisible, untimed, unfixed while everyone obsesses over 17s/line. The thing experts take for granted: that the work must be interleaved per chapter. Why? Diarize a BATCH with the LLM loaded once, persist to SQLite (you already have it), unload once, load TTS once, synthesize the whole batch — one load/unload pair per 20 chapters. The 12GB constraint is fully respected. The objection will be "power cuts," but diarization batches are short and resumable, and TTS already resumes per-line. Before any of this: have you actually profiled where a chapter's wall-clock goes with real timestamps? You have pipeline.log. If you haven't summed those columns, you're optimizing by anecdote.

### The Executor
The numbers make it obvious: loading/unloading two models per chapter across 655 chapters = ~655 LLM loads + ~655 TTS loads + ~655 VRAM barrier polls (up to 180s each). At even 60–90s overhead per chapter, that's 11–16 HOURS of VRAM spent doing nothing but swapping weights. Monday-morning fix: **batch the stages.** Diarize a RANGE with the LLM loaded once, unload, barrier ONCE, then TTS the whole range with IndexTTS2 loaded once. The orchestrator already has per-chapter status (`diarized`) — just add an outer loop. Power-cut safe because each chapter commits status to SQLite as it finishes. Second, dead-simple: fp32 → fp16, free 1.5–2x with no audible loss in an audiobook, one flag, A/B it. Third, overlooked: your CPU sits idle during TTS and your GPU sits idle during FFmpeg assembly — pipeline them (synthesize chapter N while FFmpeg assembles N-1). Don't touch num_beams again, don't chase deepspeed on Windows. Batch first.

---

## Anonymization Map

| Letter | Advisor |
|--------|---------|
| A | The Executor |
| B | The Contrarian |
| C | The First Principles Thinker |
| D | The Outsider |
| E | The Expansionist |

---

## Peer Reviews

### Reviewer 1
1. **Strongest: A** — only one that names every lever and ranks them (batch stages, fp16, plus the idle-resource pipelining of TTS(N) vs FFmpeg(N-1) that no one else spotted); notes batching is power-cut safe via per-chapter SQLite commits.
2. **Biggest blind spot: E** — "diarize ALL 655 in one continuous session" is hostile to the power-cut reality; a monolithic run guarantees no clean completion. Its re-renderable-JSON insight is the best unique idea, but the core recommendation is operationally wrong for Iraq.
3. **All missed:** Nobody questioned whether fp16 even helps — IndexTTS2 is likely bound by autoregressive per-token latency and CUDA launch overhead, not matmul, so fp16 may yield little. No one proposed actually measuring cold-load cost before optimizing. Nobody mentioned a smaller/quantized diarization LLM, or skipping the barrier poll by trusting torch's freed memory.

### Reviewer 2
1. **Strongest: A** — names the dominant cost, keeps it power-cut safe via SQLite, and is the only one to catch the CPU/GPU idle-pipelining win. E is second for the re-renderable diarized-JSON asset.
2. **Biggest blind spot: E** — "diarize ALL 655 then TTS everything" contradicts the user's hard reality of power cuts/short runs; a novel-wide pass that dies at hour 6 wastes everything not yet committed.
3. **All missed:** Validation/QA cost. With 655 chapters and an LLM that already produced misattribution bugs (ch1842/1848), generating fast is worthless if every chapter needs a manual listen-through. No automated correctness gate (flag unmapped speakers, silent lines, duration anomalies) proposed — the true bottleneck at scale is *trust*, not s/line.

### Reviewer 3
1. **Strongest: A** — only one that converts the swap tax into a concrete time estimate AND delivers three prioritized wins; respects the power-cut reality (SQLite commits) and says what NOT to do.
2. **Biggest blind spot: E** — a 300+ hour single TTS session in blackout-prone Iraq is fantasy. Best single idea (diarized JSON as reusable asset) wrapped in execution framing that ignores the hardest constraint.
3. **All missed:** The LLM stage doesn't need the 14B model. Diarization is structured classification — a 7B or 4B GGUF would cut LLM load time and VRAM pressure, possibly letting both models coexist and killing the barrier entirely. None questioned model size, only scheduling.

### Reviewer 4
1. **Strongest: A** — the only ordered, power-cut-safe plan, plus GPU/CPU pipelining and an explicit "don't touch num_beams/deepspeed." States the batching mechanism precisely (outer loop over existing `diarized` status, one barrier per range).
2. **Biggest blind spot: C** — "you don't need all 655, generate on-demand" ignores the user's actual goal (build the whole backlog) and that an offline, power-cut listener can't stream on-demand. It optimizes away the deliverable.
3. **All missed:** Batching the LLM across chapters may silently break the diarizer's *context anchoring* (a documented hard constraint) and risk blowing the 12GB ceiling — KV cache grows with batched context, so "one session" isn't free VRAM. None addressed correctness/VRAM headroom of batching; cold-load cost should be *measured from pipeline.log* first.

### Reviewer 5
1. **Strongest: A** — the full optimization stack as concrete, ordered, ready-to-build actions with the correct power-cut-safe justification, plus the CPU/GPU pipelining insight and what NOT to do.
2. **Biggest blind spot: E** — monolithic run is the worst possible shape for this user; ignores the constraint the question foregrounded. (Re-renderable-JSON point is genuinely the best idea raised.)
3. **All missed:** Whether diarization even needs the 14B model (a smaller model halves the swap tax). More fundamentally, the actual throughput ceiling is *uptime*, not s/line — an unattended auto-resume daemon that opportunistically runs TTS during power-available hours is the unaddressed lever.

---

## Chairman's Verdict

### Where the Council Agrees

All five advisors converged, independently, on one diagnosis: **the per-chapter model load/unload/VRAM-barrier cycle — paid 655 times — is the real waste, not the 17s/line.** Each estimated 11–16+ hours of pure swap overhead across the backlog. The unanimous fix is the same: **batch by stage, not by chapter.** Keep the LLM hot, diarize a *range* of chapters, unload once, cross the VRAM barrier once, then keep IndexTTS2 hot and synthesize that whole range. The orchestrator already tracks per-chapter `diarized` status in SQLite, so this is a control-flow change (an outer loop), not a model change — and it stays power-cut safe because status still commits per chapter.

Two more points drew broad agreement: (1) **fp32→fp16 is worth an A/B test** but must be *proven* by ear, not assumed; (2) **nobody has actually measured the cold-load and barrier cost** from the existing pipeline.log — the entire premise should be confirmed with real timestamps before building anything.

### Where the Council Clashes

The genuine split is **how big a batch.** The Expansionist (and partly the Outsider) pushed "diarize ALL 655 chapters in one continuous session, then TTS everything." Four of five reviewers flagged this as the council's biggest blind spot: in power-cut Iraq, a monolithic multi-hundred-hour run is the *worst* shape — it maximizes the work lost when the lights go out. The Contrarian and First Principles Thinker land in the right place: **moderate batches (≈20–50 chapters)** capture nearly all the swap savings while keeping each run short enough to survive a blackout. Reasonable advisors disagree because they're optimizing different things — the Expansionist optimizes raw overhead elimination; the others optimize *completed work per uninterrupted hour.* For this user, the second framing wins.

A secondary clash: the First Principles "generate on-demand / N-chapters-ahead" idea. Reviewer 4 rightly pushed back — the user's goal is the *whole* backlog, and an offline listener can't stream. It's a real efficiency idea but it changes the product, so treat it as optional, not core.

### Blind Spots the Council Caught

Peer review surfaced four things no single advisor said:

1. **Batching the LLM may threaten the diarizer's context anchoring** (a documented hard constraint) and KV-cache VRAM growth — "one session" is not free headroom. Batch the *scheduling* (load once, loop chapters with fresh context per chapter), not the *context*. This preserves correctness while still killing the reload tax.
2. **fp16 may underdeliver.** IndexTTS2's autoregressive stage is likely latency/launch-overhead bound, not matmul bound — so fp16 might buy far less than 2x. Test, don't assume.
3. **A smaller diarization model (7B/4B GGUF)** could halve the LLM's share of the swap tax and *possibly let both models coexist*, eliminating the barrier entirely — nobody questioned the 14B choice, only the scheduling.
4. **Trust is the real scale bottleneck.** Given prior misattribution bugs, an automated correctness gate (flag unmapped speakers, silent/zero-length lines, duration outliers) matters more than raw speed once you're processing chapters in bulk — fast generation of chapters that need manual re-listening isn't throughput.

### The Recommendation

**Batch by stage, in moderate ranges (~20–50 chapters), and measure before and after.** Concretely:

1. First, **read the numbers you already have.** Sum the load/barrier/diarize/synthesize columns in pipeline.log for a handful of recent chapters. Confirm the swap tax is really 60–90s/chapter. This converts the council's estimate into your actual number and tells you whether batching is worth it (it almost certainly is).
2. **Add an outer loop to PipelineOrchestrator:** diarize all pending chapters in the requested range with the LLM loaded once (fresh context per chapter — do *not* merge chapter contexts), unload, cross the barrier once, then synthesize the whole range with IndexTTS2 loaded once. This is the 80% win and it's power-cut safe via existing SQLite status commits.
3. Then, **cheap follow-ons:** A/B fp16 on three lines (ship only if indistinguishable); pipeline FFmpeg assembly of chapter N-1 against TTS of chapter N (idle CPU/GPU); and consider in-TTS line batching only after the stage-batching win is banked.

Do **not** re-touch num_beams, chase deepspeed on Windows, or attempt a single monolithic all-655 run.

### The One Thing to Do First

**Open pipeline.log and sum the per-stage timings for the last ~5 chapters** to get your real cold-load + barrier cost per chapter. That one number confirms the entire council's premise and tells you exactly how many hours stage-batching will save — before you write a line of code.

---

*LLM Council · June 19, 2026 · council-transcript-20260619.md*
