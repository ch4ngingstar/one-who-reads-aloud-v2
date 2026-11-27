"""Find and fix speaker labels that contradict the book.

    python scripts/audit_labels.py                      # report only
    python scripts/audit_labels.py --fix-explicit       # correct labels the book names outright
    python scripts/audit_labels.py --adjudicate         # + ask Qwen about action-beat conflicts
    python scripts/audit_labels.py --undo data/label-audit/fixes-<time>.json

A beat conflict is changed only when Qwen, reading the surrounding lines and choosing between
the current label and the book's candidate (in random order), agrees with the book - two
independent sources against one. Locked (hand-edited) lines are never touched. The database
is backed up first and every change is logged for --undo. Chapters already recorded keep
their audio until re-rendered; the affected chapters are listed.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from label_audit import find_conflicts  # noqa: E402

DB = ROOT / "src/data/pipeline.db"
LOGS = ROOT / "data/label-audit"
MODEL = ROOT / "models/Qwen3-14B-Q4_K_M.gguf"


def load_lines(con, projects):
    con.row_factory = sqlite3.Row
    marks = ",".join("?" * len(projects))
    return [dict(r) for r in con.execute(
        f"select l.id, l.chapter_id, l.line_index, l.speaker, l.kind, l.text, l.speaker_locked from lines l "
        f"join chapters c on c.id = l.chapter_id where c.project_id in ({marks})", list(projects))]


class Judge:
    """Qwen chooses between two named candidates for one quoted line."""

    def __init__(self, model):
        from llama_cpp import Llama
        self.llm = Llama(model_path=str(model), n_gpu_layers=-1, n_ctx=4096, verbose=False)

    def pick(self, conflict):
        before, quote, after = conflict["context"]
        options = [conflict["label"], conflict["evidence"]]
        if conflict["line_id"] % 2:
            options.reverse()  # no position bias towards either side
        prompt = ("Context before:\n" + "\n".join(before) + f'\n\nQUOTE: "{quote}"\n\nContext after:\n'
                  + "\n".join(after) + f"\n\nWho says the QUOTE?\nA) {options[0]}\nB) {options[1]}\n"
                  "Answer with the single letter A or B. /no_think")
        reply = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": "You identify who speaks each line of dialogue in the novel "
                                                    "Shadow Slave, using only the given text."},
                      {"role": "user", "content": prompt}], temperature=0.0, max_tokens=12)
        text = re.sub(r"<think>.*?</think>", "", reply["choices"][0]["message"]["content"], flags=re.S)
        letter = re.search(r"\b([AB])\b", text.strip().upper())
        return options[0 if letter.group(1) == "A" else 1] if letter else None


def apply(con, fixes):
    LOGS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, DB.with_name(f"pipeline.db.bak-labels-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"))
    with con:
        for fix in fixes:
            con.execute("update lines set speaker = ? where id = ?", (fix["new"], fix["line_id"]))
    log = LOGS / f"fixes-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    log.write_text(json.dumps(fixes, indent=1, ensure_ascii=False), encoding="utf-8")
    return log


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projects", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--fix-explicit", action="store_true")
    parser.add_argument("--adjudicate", action="store_true", help="Also ask Qwen about action-beat conflicts")
    parser.add_argument("--undo", type=Path)
    args = parser.parse_args(argv)
    con = sqlite3.connect(str(DB))
    if args.undo:
        fixes = json.loads(args.undo.read_text(encoding="utf-8"))
        with con:
            for fix in fixes:
                con.execute("update lines set speaker = ? where id = ?", (fix["old"], fix["line_id"]))
        print(f"Restored {len(fixes)} labels.")
        return
    conflicts = find_conflicts(load_lines(con, args.projects))
    explicit = [c for c in conflicts if c["strength"] == "explicit"]
    beats = [c for c in conflicts if c["strength"] == "beat"]
    print(f"{len(explicit)} explicit and {len(beats)} action-beat conflicts")
    fixes = []
    if args.fix_explicit or args.adjudicate:
        fixes += [{**{k: c[k] for k in ("line_id", "chapter_id", "line_index")}, "old": c["label"],
                   "new": c["evidence"], "strength": "explicit"} for c in explicit]
    if args.adjudicate and beats:
        judge = Judge(MODEL)
        agreed = 0
        for c in beats:
            if judge.pick(c) == c["evidence"]:
                agreed += 1
                fixes.append({**{k: c[k] for k in ("line_id", "chapter_id", "line_index")}, "old": c["label"],
                              "new": c["evidence"], "strength": "beat+qwen"})
        print(f"Qwen agreed with the book on {agreed} of {len(beats)} beat conflicts")
    if not fixes:
        print("Report only; nothing changed.")
        return
    log = apply(con, fixes)
    recorded = {r[0] for r in con.execute("select id from chapters where status = 'complete'")}
    stale = sorted({f["chapter_id"] for f in fixes} & recorded)
    print(f"Relabelled {len(fixes)} lines in {len({f['chapter_id'] for f in fixes})} chapters "
          f"({len(stale)} already recorded need a re-render). Undo: python scripts/audit_labels.py --undo \"{log}\"")


if __name__ == "__main__":
    main()
