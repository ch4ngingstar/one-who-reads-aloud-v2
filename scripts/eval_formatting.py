"""
Formatting / diarization accuracy evaluation — how good are the speaker + emotion
labels the local LLM assigns, measured against a trusted gold set?

Compares the live DB labels (get_lines_for_chapter) against a gold label file for
the same chapter (produced via scripts/diarize_io.py export → cloud LLM →
spot-correct). Reports speaker-label accuracy, emotion-label accuracy, both
confusion breakdowns, and how many gold/predicted speakers would resolve to an
unmapped voice at TTS time (reusing qa_audit._resolve_category).

Segmentation (Pass 1) is byte-exact, so a line-count/index mismatch between gold
and DB is itself a finding.

Read-only. Run from repo root:
    python scripts/eval_formatting.py --chapter 264 --by-index --gold tests/data/gold/ch_264.json
"""

import argparse
import json
import sys
from pathlib import Path

from eval_common import (
    DEFAULT_DB, REPORTS_DIR, pick_project, chapter_id_for_index, write_json,
)


def load_gold(path: Path) -> dict:
    """Parse a gold label file into {line_index: (speaker, emotion)}.

    Accepts either the cloud/export shape {"labels": [{"i","speaker","emotion"}]}
    or a bare list of {"line_index"|"i", "speaker", "emotion"}.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["labels"] if isinstance(data, dict) and "labels" in data else data
    out = {}
    for it in items:
        idx = it.get("line_index", it.get("i"))
        if idx is None:
            raise ValueError(f"gold entry missing line_index/i: {it}")
        out[int(idx)] = (it["speaker"], it["emotion"])
    return out


def labels_from_db(sm, chapter_id: int) -> dict:
    """{line_index: (speaker, emotion)} from the live DB."""
    return {ln["line_index"]: (ln["speaker"], ln["emotion"])
            for ln in sm.get_lines_for_chapter(chapter_id)}


def compare_labels(pred: dict, gold: dict) -> dict:
    """Speaker/emotion accuracy + confusion + mismatches over the shared indices."""
    shared = sorted(set(pred) & set(gold))
    missing_in_pred = sorted(set(gold) - set(pred))
    missing_in_gold = sorted(set(pred) - set(gold))

    sp_correct = emo_correct = 0
    sp_conf, emo_conf, mismatches = {}, {}, []
    for i in shared:
        gs, ge = gold[i]
        ps, pe = pred[i]
        if ps == gs:
            sp_correct += 1
        else:
            sp_conf.setdefault((gs, ps), 0)
            sp_conf[(gs, ps)] += 1
        if pe == ge:
            emo_correct += 1
        else:
            emo_conf.setdefault((ge, pe), 0)
            emo_conf[(ge, pe)] += 1
        if ps != gs or pe != ge:
            mismatches.append({"line_index": i, "gold_speaker": gs, "pred_speaker": ps,
                               "gold_emotion": ge, "pred_emotion": pe})
    n = len(shared)
    return {
        "n_shared": n,
        "speaker_accuracy": round(sp_correct / n, 4) if n else None,
        "emotion_accuracy": round(emo_correct / n, 4) if n else None,
        "speaker_confusion": {f"{g}->{p}": c for (g, p), c in
                              sorted(sp_conf.items(), key=lambda kv: -kv[1])},
        "emotion_confusion": {f"{g}->{p}": c for (g, p), c in
                              sorted(emo_conf.items(), key=lambda kv: -kv[1])},
        "mismatches": mismatches,
        "missing_in_pred": missing_in_pred,
        "missing_in_gold": missing_in_gold,
    }


def resolution_summary(label_map: dict, voice_map: dict) -> dict:
    """How the speakers in a label map would resolve to voices (mapped/fallback/unmapped)."""
    from qa_audit import _resolve_category

    counts = {"mapped": 0, "fallback": 0, "unmapped": 0}
    unmapped_speakers = set()
    for (sp, emo) in label_map.values():
        cat = _resolve_category(sp, emo, voice_map)
        counts[cat] += 1
        if cat == "unmapped":
            unmapped_speakers.add(sp)
    return {"counts": counts, "unmapped_speakers": sorted(unmapped_speakers)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Diarization/formatting accuracy vs gold.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--project", default=None)
    ap.add_argument("--chapter", type=int, required=True,
                    help="chapter id (or chapter_index with --by-index)")
    ap.add_argument("--by-index", action="store_true")
    ap.add_argument("--gold", required=True, help="gold label JSON for this chapter")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from state_manager import StateManager
    sm = StateManager(args.db)
    project_id = pick_project(sm, args.project)
    cid = (chapter_id_for_index(sm, project_id, args.chapter)
           if args.by_index else args.chapter)
    if cid is None:
        print(f"[eval] chapter not found.", file=sys.stderr)
        sys.exit(2)

    gold = load_gold(Path(args.gold))
    pred = labels_from_db(sm, cid)
    cmp = compare_labels(pred, gold)
    voice_map = sm.get_voice_map()
    report = {
        "chapter_id": cid,
        "comparison": cmp,
        "resolution_pred": resolution_summary(pred, voice_map),
        "resolution_gold": resolution_summary(gold, voice_map),
    }

    out = args.out or str(REPORTS_DIR / f"eval_formatting_ch{cid}.json")
    write_json(Path(out), report)

    print(f"[eval] chapter_id={cid}: shared lines={cmp['n_shared']}")
    print(f"  speaker accuracy = {cmp['speaker_accuracy']}")
    print(f"  emotion accuracy = {cmp['emotion_accuracy']}")
    if cmp["missing_in_pred"] or cmp["missing_in_gold"]:
        print(f"  INDEX MISMATCH — missing_in_pred={len(cmp['missing_in_pred'])} "
              f"missing_in_gold={len(cmp['missing_in_gold'])} (segmentation should be 1:1)")
    if cmp["speaker_confusion"]:
        top = list(cmp["speaker_confusion"].items())[:5]
        print("  top speaker confusions: " + ", ".join(f"{k}({v})" for k, v in top))
    print(f"[eval] wrote {out}")


if __name__ == "__main__":
    main()
