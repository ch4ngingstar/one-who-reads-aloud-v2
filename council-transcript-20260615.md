# LLM Council Transcript — June 15, 2026

## Original Question

"The current state of the project — should or shouldn't we try to find a way to improve it and make the performance better + make the UI better or not, or anything you recommend doing?"

## Framed Question

"One Who Reads Aloud" is a working, local audiobook pipeline for the Shadow Slave web novel (public GitHub repo, MIT license). It parses EPUBs, diarizes each chapter via a local 14B GGUF LLM, synthesizes speech with IndexTTS2 (emotion-vector-per-line), and assembles MP3s. Tech: Python/FastAPI backend + Next.js 15 UI.

Current state as of June 2026: Pipeline works E2E (~11–17 s/line for TTS, ~45 s to diarize a chapter). UI was heavily overhauled 2 weeks ago (dark Shadow Slave theme, chapter grid, global player, toast system). 410+ chapters remaining unprocessed. Repo is public. README lacks an audio demo sample.

The question: Should the next investment go into (a) performance optimization of the pipeline, (b) further UI improvements, (c) something else entirely? What's the highest-leverage next move, and is there a hidden priority the user might be missing?

---

## Advisor Responses

### The Contrarian

The question is framed wrong, and that's the first flaw to fix.

You're debating UI polish versus performance when neither addresses the actual bottleneck: you have 410+ chapters to process and a sequential pipeline that cannot run unattended overnight without human babysitting.

What fails at scale that nobody is asking about?

Failure recovery at chapter-volume scale. The resume logic handles `diarized` and `error` states, but what happens at hour 6 of a batch run when the VRAM barrier poll hangs, a GGUF context overflows on an unusually long chapter, or FFmpeg silently produces a corrupt MP3? Does the orchestrator catch that, log it clearly, and continue to the next chapter — or does the whole batch die and you wake up to nothing?

The 410-chapter math is brutal. At 45 seconds to diarize plus (say) 200 lines × 14 seconds = ~47 minutes TTS per chapter, that's roughly 350+ hours of wall-clock time. Sequential. Single machine. 12 GB VRAM constraint means no parallelism between LLM and TTS. You need that pipeline to run for weeks without intervention.

Before performance optimization or UI improvements, the hidden priority is **unattended reliability**: robust chapter-level error isolation, a dead-man's-switch that resumes from exactly the right state after a crash or reboot, and a health-check log you can glance at in the morning to confirm it's still running.

The audio demo is also genuinely blocked and matters more than either option listed — a public repo with no audio sample gets zero traction. Fix that first, it takes one hour.

---

### The First Principles Thinker

The question assumes the bottleneck is the pipeline or the UI. Strip that assumption away.

You have 410+ chapters of a single web novel. At 11–17 s/line and roughly 50–200 lines per chapter, you are looking at 6–28 hours of compute per chapter, unattended, on a single machine with a hard VRAM sequencing constraint. The real question is not "what feature next?" — it is "will this machine ever finish the job?"

Do the math first. How many lines total across 410 chapters? Multiply by your median TTS time. If the answer is 300+ hours of GPU time, no UI improvement matters. No optimization that yields 2× speedup matters enough either unless it crosses a threshold where completion becomes realistic within your horizon.

The hidden priority is completion feasibility, not quality of the tooling.

First principles question: what is the actual goal? If it is "produce a complete Shadow Slave audiobook for personal enjoyment," the highest-leverage move is not more code — it is understanding whether this architecture can reach the finish line on this hardware within a realistic timeframe, and if not, what changes that calculus (cloud burst, batching, a cheaper TTS model, scope reduction to favorite chapters only).

The README missing an audio demo is actually the most revealing signal here: you are building infrastructure for a product that does not yet exist in listenable form. Prove the end product works at scale before optimizing the factory.

Concrete next move: run the completion math. If the number is acceptable, batch-run chapters autonomously. If not, that is the only problem worth solving.

---

### The Expansionist

The audio demo gap is the highest-leverage move, and it's being wildly undervalued.

You have a working pipeline, a public repo, an MIT license, and a genuinely impressive technical story — local LLM diarization with per-line emotion vectors driving IndexTTS2. That combination is rare. But right now nobody can *hear* it, which means the repo's viral potential is essentially zero.

Add one 60–90 second audio sample to the README and you unlock a completely different trajectory. Web novel communities (Royal Road, Scribble Hub, Reddit's r/noveltranslations, the Shadow Slave Discord) will share it. TTS and audiobook hobbyist communities will share it. HuggingFace/GitHub ML crowds will star it. A working demo of emotion-vector-controlled zero-shot voice cloning on a 12 GB consumer GPU is genuinely interesting to a lot of people, not just Shadow Slave fans.

That audience expansion is the hidden upside. Right now the project solves a personal problem. A demo makes it a *reference implementation* — the thing people fork when they want to do this for their own EPUB library, their own fanfic, their own web novel. That's a completely different surface area.

From there the adjacent opportunity becomes obvious: a one-command Docker image or a `pip install` CLI that accepts any EPUB. The architecture already abstracts speaker/voice/emotion cleanly. The jump from "personal pipeline" to "the go-to open-source EPUB-to-audiobook tool with emotion synthesis" is not that far.

Performance optimization on 410 chapters is a treadmill. UI polish is invisible to anyone who hasn't cloned it yet.

Get the demo out first. Everything else compounds on top of that.

---

### The Outsider

The README lacks an audio demo. That is the only thing that matters right now.

You have a public repo with zero proof it works. A visitor lands, reads "synthesizes speech with emotion vectors," sees a technical architecture diagram, and has no idea if the output sounds like a robot or a human. They close the tab. The performance numbers (11–17 s/line, 45 s/chapter) mean nothing without hearing what those seconds produced.

This is the classic expert blind spot: you know the output sounds good because you've heard it hundreds of times across 410 chapters. Everyone else sees a pipeline description and assumes it's a toy project.

The "README lacks audio demo" note in your own memory file has been marked PENDING for two weeks. That delay tells me it feels optional. It is not optional — it is the entire value proposition made tangible.

The hidden priority: before optimizing performance or improving UI, you need one 60-second MP3 clip, publicly hosted (GitHub release asset, Soundcloud, anything), linked in the README with a single sentence: "Here's what chapter 264 sounds like." That single addition converts skeptics into interested contributors or users faster than any feature.

Performance optimization at 410 chapters unprocessed is a fine eventual goal. UI polish on a project with no proven audience is premature. But proof-of-quality is the unlock for everything else — contributors, feedback, motivation to keep going.

The audio demo isn't blocked on a free GPU. You already have processed chapters. Pick the best 60 seconds from chapter 264, export it, host it, link it. That's a 30-minute task you've been treating as a project.

---

### The Executor

The numbers make the decision obvious: 655 pending chapters, 15 complete. The pipeline works but it's glacially slow at scale.

At 11–17 s/line and roughly 30–60 lines per chapter, you're looking at 6–10 minutes per chapter for TTS alone. 655 chapters unprocessed means 65–110 hours of compute left. That's the only number that matters right now.

**The Monday-morning move is batch throughput, not UI.**

1. **Run the pipeline unattended overnight.** Does it actually do that? If it crashes on error chapters and stops, fix the error-handling loop in the orchestrator so it skips and continues. One evening of work, potentially recovers 8+ hours of processing per night.
2. **Profile where time actually goes.** Is the 11–17 s/line all GPU synthesis, or is there overhead (file I/O, voice resolution, WAV concatenation) eating 30–40% of it? If overhead is significant, it's free time to reclaim without touching the model.
3. **The audio demo blocker is real but second-priority.** The README lacks a sample and the repo is public. Nobody will use or share a project with no audio proof. That's a 30-minute task once you pick 30 seconds of a completed chapter.

UI is done. Performance optimization for throughput (not latency) is the lever. The hidden priority is unattended overnight batch running — if that's not bulletproof today, fix it first.

---

## Anonymization Map

| Letter | Advisor |
|--------|---------|
| A | First Principles Thinker |
| B | Executor |
| C | Contrarian |
| D | Expansionist |
| E | Outsider |

---

## Peer Reviews

### Reviewer 1
1. **Strongest: C (Contrarian)** — Only one that identifies actual technical risk at scale. Combines the completion math with concrete failure mode analysis. Also correctly notes the audio demo priority without making it the entire answer.
2. **Biggest blind spot: E (Outsider)** — Treats audio demo as the *only* thing that matters. A repo with a clip but a pipeline that dies after 6 hours of batch processing is still a dead project. Rushing a mediocre clip could actively hurt credibility.
3. **All five missed:** Copyright. "Shadow Slave" is licensed. Publishing synthesized audio publicly may violate the author's rights. MIT covers the pipeline code, not derivative audio works from copyrighted text.

### Reviewer 2
1. **Strongest: C (Contrarian)** — Correctly identifies specific technical failure modes and connects to the actual risk of a multi-week batch dying at hour 6.
2. **Biggest blind spot: E (Outsider)** — Ignores that the user's goal is personal enjoyment of 410 chapters, not repo traction. Optimizing for GitHub stars when the pipeline can't survive an overnight run unattended is exactly backwards.
3. **All five missed:** None of them asked whether the pipeline currently runs unattended at all. The actual first move is an observed overnight batch run to collect failure data. Measure before prescribing.

### Reviewer 3
1. **Strongest: C (Contrarian)** — Only one that identifies actual technical risk, names failure modes, quantifies the ~350 hour run time.
2. **Biggest blind spot: E (Outsider)** — Treats audio demo as singular unlock, ignores user's own stated blocker (voice choice + free GPU). Not a 30-minute task.
3. **All five missed:** Chapter ordering strategy. With 410+ chapters unprocessed, prioritizing in reading order means every completed chapter is immediately useful. Zero-code, zero-cost, directly serves the actual goal.

### Reviewer 4
1. **Strongest: C (Contrarian)** — Thinks through failure modes at scale, names specific failure modes (VRAM barrier hang, GGUF context overflow, silent FFmpeg corruption).
2. **Biggest blind spot: E (Outsider)** — Ignores that memory file says demo is "blocked on user's voice choice + free GPU."
3. **All five missed:** Does the EPUB source stay current? Shadow Slave is an ongoing serial. Every new chapter may require manual re-parse. If manual, the ops burden compounds indefinitely.

### Reviewer 5
1. **Strongest: C (Contrarian)** — Identifies the real constraint: pipeline must run unattended for weeks. Names failure modes. Quantifies the math.
2. **Biggest blind spot: D (Expansionist)** — Argues audio demo unlocks viral growth, but distributing synthesized audio of copyrighted content publicly raises real copyright questions.
3. **All five missed:** Storage and disk I/O at scale. 410 chapters × 200 lines × WAV files = 80,000+ intermediate files and potentially 30–60 GB of disk. Could become the binding constraint before GPU time.

---

## Chairman's Verdict

### Where the Council Agrees

Every advisor independently reached the same conclusion: the audio demo should exist and currently does not. This is a high-confidence signal — the absence is real and the fix is cheap.

More importantly, four of five advisors converged on a second point: the pipeline's ability to run **unattended at scale** is the actual constraint, and nobody has measured it directly. The Executor put numbers on it (65–110 hours of compute remaining). The Contrarian named the failure modes (VRAM barrier hangs, context overflows on long chapters, FFmpeg silent corruption). The First Principles Thinker framed the stakes: at 300+ hours of sequential GPU time, a pipeline that dies at hour 6 and loses its state is not a slow pipeline — it is a broken one.

**The council agrees: UI is done. "Make TTS faster" is not the priority. Batch throughput and survivability are.**

### Where the Council Clashes

The genuine disagreement is between the Expansionist/Outsider camp (audio demo is the unlock for everything) and the Contrarian/Reviewer camp (audio demo is secondary, and publishing synthesized audio of "Shadow Slave" may raise copyright issues).

The Expansionist argues this pipeline is technically rare and a 60-second clip could trigger real community interest. The Outsider calls the two-week delay a psychological tell.

The reviewers push back: "Shadow Slave" is a licensed work under Kharn Ding (Xiaoman). MIT covers the code, not derivative audio works. The user's own memory file records the demo as "blocked on user's voice choice + free GPU" — the Outsider's "30-minute task" framing is factually wrong.

The disagreement resolves this way: the demo matters, but it cannot be treated as a free, zero-risk action. **The copyright question must be answered before anything is published publicly.**

### Blind Spots the Council Caught

**Copyright (3/5 reviewers flagged independently):** Publishing synthesized audio derived from a copyrighted web novel is not covered by MIT. Before any public audio demo, the options are: get explicit permission from the author, use a public-domain text for the demo clip, or keep the demo private/unlisted.

**Storage at scale:** 410+ chapters × ~200 lines each × 1 WAV per line = 80,000+ intermediate files and potentially 30–60 GB of disk before WAVs are cleaned up after assembly. If WAVs are not deleted on chapter completion, disk space may become the binding constraint before GPU time does.

**Chapter ordering strategy:** There is no guarantee the pipeline is running chapters in reading order. Processing sequentially from where the user is in the novel means every completed chapter is immediately listenable. Zero-code, zero-cost.

### The Recommendation

Fix unattended batch reliability first. Everything else is irrelevant if the pipeline dies at 2 AM and resumes from the wrong state.

The orchestrator needs verified chapter-level error isolation: a single chapter failure must log the error, mark the chapter `error`, and advance to the next chapter automatically.

A 20% TTS speedup saves 13–22 hours. Fixing a bug that causes the pipeline to die and restart from scratch saves all of it.

On the audio demo: the right move is a private or unlisted clip first. Do not post public synthesized Shadow Slave audio before resolving the copyright question with the author.

### The One Thing to Do First

Run the pipeline unattended overnight on 10 consecutive chapters and read the log in the morning. Do not fix anything yet — just observe. If it completes all 10, your batch infrastructure is sound and you move to the demo and storage hygiene. If it stops before 10, the failure mode it exposes is the only problem worth solving right now.

---

*LLM Council · June 15, 2026 · council-transcript-20260615.md*
