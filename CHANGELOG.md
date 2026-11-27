# Changelog

All notable changes to this project. Versions follow [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-11-27 · *Who Is Speaking*

The labelling was rebuilt from the text up and measured against hand-checked answer keys. On held-out chapters speaker attribution went from about 60% to 94.6% fully automatic and 98.6% after the flagged lines are reviewed.

### Text
- **Complete chapters.** Chapters are re-read from the EPUB. Volumes 8–9 had lost about 15% of their paragraphs (2,561 + 2,825, including ~1,470 lines of dialogue) to an older parser; they are restored when a chapter is labelled.
- **Quote scanner.** A position-based scanner replaces pairing by glyph. «Guillemets», quotes that open with one mark and close with another, quotes that run to the paragraph end and scraper glitches are understood. Quoted paragraphs read by the narrator by mistake: about 2,400 → 14.
- **Watermark scrubber.** About 60 injected site watermarks, disguised with small capitals, Cyrillic look-alikes and symbols, are removed before narration.
- Bracketed telepathy inside narration becomes its own line. Narration that says "I" or "you" is checked for lost quote marks.

### Labelling
- **Evidence engine.** Attribution tags, he/she introductions resolved by gender, action beats, names used as address, self-introductions, unnamed people and relations ("Ling's dad"), conditional descriptions ("her teacher" = Sunny in Rain's chapters), new names found in the text and OCR-style typos of known names.
- **Character sheet.** `profiles/characters.json`: genders, aliases, notes and companions for 47 speakers.
- **Qwen3-14B labeller.** Two independent multiple-choice passes over a prefix-cached chapter, with a reasoning tiebreak.
- **Gemma 3 second opinion.** A blind vote from a different model family. Lines where every vote agrees: 98.4% correct on held-out chapters.
- **Emotion gate.** Whispering, laughing, coldness and command require the narration's own words.
- **Answer keys and scorer.** `scripts/label_eval.py`; two independent annotators per chapter (99.7% / 100% agreement).

### Studio
- **New demo.** *The Bridge in the Fog*, an original scene recorded with the directed cast (eight voices, inner monologue, a whisper and a Spell message). `scripts/render_demo.py` re-records it.
- **Start labels what you pick.** `LabelDirector` replaces the old diarizer: choose a range, press Start, and the chosen chapters are labelled, checked, stored and recorded. Chapters still carrying older labels are relabelled first.
- **Review queue.** Inspector → *Needs review · N* lists flagged lines with the reason, the votes and one-click **✓ … is right**. Choosing a new speaker also settles the flag.
- **Stand-in voices.** Speakers without a cast voice get a gender-matched stand-in instead of the narrator's voice.
- New EPUBs are kept in `data/input/` so they can always be re-read.

### Cast and recording (since 0.2.0)
- **Directed cast by blind listening.** OmniVoice for the narrator, Sunny, Anvil, Cassie and Seishan; Fish S2 Pro (Q8_0 via audio.cpp) for the other characters. 12 designed voices plus the owner's own clips for Jet, Effie, Nephis and Beth.
- **Casting toolkit.** `scripts/cast.py discover | screen | apply`: discovery, voice briefs, designed candidates, automatic screening (read-back, pitch range, distinctness) and blind casting pages.
- **Delivery cues for Fish** kept only where a blind vote preferred them; a character's habitual emotion is not treated as a mood.
- **Production polish.** Per-actor loudness balancing, natural pauses for paragraphs and turns, edge trimming, reference fitting, Whisper read-back with retakes, real chapter numbers and titles in file names and ID3 tags, M4B export with chapter marks.

### Fixed
- Chapter files and the UI now use the real chapter number and title rather than the EPUB position.
- Yutra's gender (male) and several aliases.
- `soundfile` was missing from `requirements.txt`.

## [0.2.0] — 2026-06-28 · *Sound Design Layer*

Optional cinematic ambience, sound effects and music cues with a UI Sound tab, a 40-tag library and a procedural FFmpeg fallback.

## [0.1.0] — 2026-06-21 · *Correctness & Emotion-Quality Pass*

External diarization (bring your own labels), a read-only correctness audit, greedy decoding for faster TTS, segmenter fixes for wrong-handed quotes, emotion retuning and a Windows encoding crash fix.

[0.3.0]: https://github.com/ch4ngingstar/one-who-reads-aloud-v2/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ch4ngingstar/one-who-reads-aloud-v2/releases/tag/v0.2.0
[0.1.0]: https://github.com/ch4ngingstar/one-who-reads-aloud-v2/releases/tag/v0.1.0
