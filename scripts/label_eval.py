"""Score speaker / kind / emotion labels against the hand-checked gold set.

    python scripts/label_eval.py agree data/label-gold/annotator_A data/label-gold/annotator_B
    python scripts/label_eval.py score data/labels/qwen-v1 [--gold data/label-gold/gold] [--show 30]

Speakers match when their canonical names match. Two unnamed speakers match when
their genders do not contradict (the voice comes from a gendered pool, so the exact
role word does not change the audio). An emotion is right when it is the gold
emotion or one of the gold's acceptable alternatives. The four emotions that change
the Fish delivery are also scored for precision and recall.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_bible import NARRATOR, UNNAMED_PREFIX, Bible  # noqa: E402

GOLD = ROOT / "data" / "label-gold" / "gold"
ACTIONABLE = ("whispers", "commanding", "cold", "laughing")
_KIND = {"speech": "spoken", "telepathy": "spoken", "dialogue": "spoken", "thought": "thought",
         "system": "system", "narration": "narration", "prose": "narration"}


def load(folder: Path) -> "dict[int, dict[int, dict]]":
    """chapter number -> segment index -> label."""
    out = {}
    for path in sorted(Path(folder).glob("ch_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        number = int(data.get("chapter") or path.stem.split("_")[1])
        out[number] = {int(label.get("i", label.get("index"))): label for label in data["labels"]}
    return out


def same_speaker(bible: Bible, a: dict, b: dict) -> bool:
    """``b`` is the reference; its ``speaker_ok`` lists other acceptable answers."""
    alternatives = [dict(b, speaker=name) for name in b.get("speaker_ok", [])]
    return any(_same(bible, a, ref) for ref in [b, *alternatives])


def _same(bible: Bible, a: dict, b: dict) -> bool:
    sa, sb = a.get("speaker", ""), b.get("speaker", "")
    if sa.startswith(UNNAMED_PREFIX) and sb.startswith(UNNAMED_PREFIX):
        ga, gb = a.get("gender", "unknown"), b.get("gender", "unknown")
        return "unknown" in (ga, gb) or ga == gb
    return (bible.canonical(sa) or sa) == (bible.canonical(sb) or sb)


def kind_of(label: dict) -> str:
    return _KIND.get(label.get("kind", ""), label.get("kind", ""))


def emotion_ok(predicted: dict, gold: dict) -> bool:
    return predicted.get("emotion", "neutral") in {gold.get("emotion", "neutral"), *gold.get("emotion_ok", [])}


def _in_options(bible: Bible, p: dict, g: dict) -> bool:
    gold = bible.canonical(g["speaker"]) or g["speaker"]
    options = p.get("options", [])
    return gold in options or (g["speaker"].startswith(UNNAMED_PREFIX) and "@other" in options)


def compare(bible: Bible, predicted, gold) -> Counter:
    stats = Counter()
    stats["actionable"] = {e: Counter() for e in ACTIONABLE}
    stats["misses"] = []
    for chapter, gold_labels in gold.items():
        mine = predicted.get(chapter)
        if mine is None:
            continue
        for index, g in gold_labels.items():
            p = mine.get(index) or {"speaker": NARRATOR, "kind": "narration", "emotion": "neutral"}
            stats["lines"] += 1
            stats["kind_ok"] += kind_of(p) in {kind_of(g), *(_KIND.get(k, k) for k in g.get("kind_ok", []))}
            if kind_of(g) == "narration":
                continue
            stats["quotes"] += 1
            ok = same_speaker(bible, p, g)
            stats["speaker_ok"] += ok
            if "options" in p:
                stats["recall_n"] += 1
                stats["recall_ok"] += ok or _in_options(bible, p, g)
            flagged = bool(p.get("review"))
            stats["review"] += flagged
            stats["review_wrong"] += flagged and not ok
            stats["emotion_ok"] += emotion_ok(p, g)
            for e in ACTIONABLE:
                said, accepted = p.get("emotion") == e, e in {g.get("emotion"), *g.get("emotion_ok", [])}
                cell = "tp" if said and accepted else "fp" if said else "fn" if g.get("emotion") == e else "tn"
                stats["actionable"][e][cell] += 1
            if not ok:
                stats["misses"].append((chapter, index, p.get("speaker"), g.get("speaker"), p.get("how", ""),
                                        g.get("note", "")[:70]))
    return stats


def report(stats: Counter, show: int) -> None:
    q = stats["quotes"] or 1
    print(f"quoted lines: {stats['quotes']}   speaker accuracy: {stats['speaker_ok'] / q:.1%}"
          f"   kind accuracy: {stats['kind_ok'] / max(stats['lines'], 1):.1%}"
          f"   emotion acceptable: {stats['emotion_ok'] / q:.1%}")
    if stats["recall_n"]:
        print(f"true speaker among the candidates: {stats['recall_ok'] / stats['recall_n']:.1%}")
    if stats["review"]:
        unflagged_ok = stats["speaker_ok"] - (stats["review"] - stats["review_wrong"])
        print(f"flagged for review: {stats['review']} ({stats['review'] / q:.1%}), {stats['review_wrong']} of them wrong;"
              f" unflagged accuracy {unflagged_ok / max(q - stats['review'], 1):.1%};"
              f" after fixing flagged lines by hand {(stats['speaker_ok'] + stats['review_wrong']) / q:.1%}")
    for e, c in stats["actionable"].items():
        precision = c["tp"] / max(c["tp"] + c["fp"], 1)
        recall = c["tp"] / max(c["tp"] + c["fn"], 1)
        print(f"  {e:11s} predicted {c['tp'] + c['fp']:3d}  precision {precision:.0%}  recall {recall:.0%}")
    for miss in stats["misses"][:show]:
        print("  miss ch%s #%s: got %s, gold %s [%s] %s" % miss)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    agree = sub.add_parser("agree")
    agree.add_argument("a", type=Path)
    agree.add_argument("b", type=Path)
    score = sub.add_parser("score")
    score.add_argument("labels", type=Path)
    score.add_argument("--gold", type=Path, default=GOLD)
    for p in (agree, score):
        p.add_argument("--show", type=int, default=40)
    args = parser.parse_args(argv)
    bible = Bible.load()
    if args.cmd == "agree":
        report(compare(bible, load(args.a), load(args.b)), args.show)
    else:
        report(compare(bible, load(args.labels), load(args.gold)), args.show)


if __name__ == "__main__":
    main()
