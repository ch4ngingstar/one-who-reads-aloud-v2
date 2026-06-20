"""
Run the full evaluation harness over a corpus and write one Markdown report.

Runs the CPU scorers — accuracy (ASR/WER), speaker consistency, and (where a gold
file exists) formatting accuracy — for each requested chapter, plus a one-shot
roster audit. Folds in the emotion delta matrix from a prior
`scripts/eval_emotion.py` run if docs/eval_emotion.json is present (that step is
GPU-only and run separately).

Read-only. Run from repo root:
    python scripts/eval_all.py --chapter 264 --by-index --gold-dir tests/data/gold
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from eval_common import (
    DEFAULT_DB, REPORTS_DIR, pick_project, resolve_chapter_ids,
    chapter_id_for_index, append_markdown,
)
import eval_accuracy
import eval_speaker
import eval_formatting
import eval_roster


def _gold_for(gold_dir: "Path | None", chapter_id: int, chapter_index: "int | None"):
    if not gold_dir:
        return None
    for cand in (f"ch_{chapter_index}.json" if chapter_index is not None else None,
                 f"ch_{chapter_id}.json"):
        if cand and (gold_dir / cand).exists():
            return gold_dir / cand
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the whole eval harness → one report.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--project", default=None)
    ap.add_argument("--chapter", type=int, nargs="*", default=None)
    ap.add_argument("--by-index", action="store_true")
    ap.add_argument("--gold-dir", default=None)
    ap.add_argument("--epub", default=None)
    ap.add_argument("--whisper-model", default="base")
    ap.add_argument("--skip-accuracy", action="store_true")
    ap.add_argument("--skip-speaker", action="store_true")
    ap.add_argument("--skip-roster", action="store_true")
    args = ap.parse_args()

    from state_manager import StateManager
    sm = StateManager(args.db)
    project_id = pick_project(sm, args.project)
    chapter_ids = resolve_chapter_ids(sm, project_id, args.chapter, args.by_index)
    if not chapter_ids:
        print("[eval] No chapters with diarized lines.", file=sys.stderr)
        sys.exit(2)

    gold_dir = Path(args.gold_dir) if args.gold_dir else None
    report = REPORTS_DIR / f"eval-report-{date.today().isoformat()}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"# Evaluation Report — {date.today().isoformat()}\n\n", encoding="utf-8")

    # index lookup for nicer labels + gold filenames
    idx_of = {ch["id"]: ch["chapter_index"] for ch in sm.get_all_chapters(project_id)}

    transcribe = None
    if not args.skip_accuracy:
        print(f"[eval] loading faster-whisper '{args.whisper_model}'...")
        transcribe = eval_accuracy.load_whisper(args.whisper_model)
    embed = None
    if not args.skip_speaker:
        print("[eval] loading resemblyzer encoder...")
        embed = eval_speaker.load_encoder()
    voice_map = sm.get_voice_map()

    for cid in chapter_ids:
        ci = idx_of.get(cid)
        append_markdown(report, f"## Chapter {ci} (id={cid})")

        if transcribe is not None:
            acc = eval_accuracy.score_chapter(sm, cid, transcribe)
            append_markdown(report,
                f"**Accuracy** — scored {acc['n_scored']} lines, "
                f"mean WER {acc['mean_wer']}, mean CER {acc['mean_cer']}, "
                f"{acc['n_flagged']} flagged (≥0.4 WER), {acc['n_missing']} missing audio.")

        if embed is not None:
            spk = eval_speaker.score_chapter(sm, cid, voice_map, embed)
            worst = sorted(spk["per_speaker"].items(), key=lambda kv: kv[1])[:5]
            worst_md = ", ".join(f"{s}={v}" for s, v in worst) or "—"
            append_markdown(report,
                f"**Voice consistency** — scored {spk['n_scored']} lines, "
                f"mean similarity {spk['mean_sim']}, {spk['n_flagged']} below 0.75.\n\n"
                f"Lowest-similarity speakers: {worst_md}")

        gold = _gold_for(gold_dir, cid, ci)
        if gold:
            pred = eval_formatting.labels_from_db(sm, cid)
            cmp = eval_formatting.compare_labels(pred, eval_formatting.load_gold(gold))
            top = list(cmp["speaker_confusion"].items())[:5]
            top_md = ", ".join(f"{k}({v})" for k, v in top) or "—"
            append_markdown(report,
                f"**Formatting vs gold** ({gold.name}) — {cmp['n_shared']} shared lines, "
                f"speaker acc {cmp['speaker_accuracy']}, emotion acc {cmp['emotion_accuracy']}.\n\n"
                f"Top speaker confusions: {top_md}")
        elif gold_dir:
            append_markdown(report, "_No gold file found for this chapter — formatting skipped._")

    # Emotion (folded in from a prior GPU run)
    emo_json = REPORTS_DIR / "eval_emotion.json"
    if emo_json.exists():
        emo = json.loads(emo_json.read_text(encoding="utf-8"))
        inert = emo.get("inert_tags", [])
        append_markdown(report, "## Emotion-vector effect")
        append_markdown(report,
            f"Inert tags (no measurable prosody change vs neutral): "
            f"**{', '.join(inert) if inert else 'none — all tags move the voice'}**. "
            f"See docs/eval_emotion.csv for the full delta matrix.")
    else:
        append_markdown(report, "## Emotion-vector effect")
        append_markdown(report, "_Run `python scripts/eval_emotion.py --ref <voice.wav>` "
                                "(GPU) to populate this section._")

    if not args.skip_roster:
        append_markdown(report, "## Roster coverage (post-Vol-9)")
        try:
            epub = Path(args.epub) if args.epub else next(iter(eval_roster.ROOT.glob("**/*.epub")), None)
            if epub:
                text = eval_roster._load_chapter_texts(epub, 0)
                ra = eval_roster.audit(text)
                top = ra["uncovered"][:15]
                lines = "\n".join(f"- {r['name']} ({r['count']})" for r in top) or "- none"
                append_markdown(report,
                    f"{len(ra['uncovered'])} uncovered attributed names. Top:\n\n{lines}")
            else:
                append_markdown(report, "_No EPUB found — pass --epub to enable roster audit._")
        except Exception as e:  # roster is best-effort; never fail the whole report
            append_markdown(report, f"_Roster audit error: {e}_")

    print(f"[eval] wrote {report}")


if __name__ == "__main__":
    main()
