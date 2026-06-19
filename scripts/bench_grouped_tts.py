"""Measure the speaker-grouped synthesis win (IndexTTS2 conditioning-cache reuse).

IndexTTS2 caches the speaker conditioning for the LAST spk_audio_prompt only, so
alternating dialogue (A,B,A,B…) recomputes that costly conditioning on every
turn. tts_engine now synthesises lines grouped by reference audio so the cache
hits on every line after a speaker's first. This script times a real chapter's
lines synthesised in LINE order vs GROUPED order on YOUR GPU and reports the
speedup — the magnitude depends on how dialogue-interleaved the chapter is.

Read-only: it never writes WAVs into the pipeline tree or touches the DB status.
It loads IndexTTS2 once and synthesises to throwaway temp files.

Run from repo root (needs the GPU + IndexTTS2 weights):
    python scripts/bench_grouped_tts.py --chapter 270
    python scripts/bench_grouped_tts.py            # auto-pick a dialogue-heavy chapter
    python scripts/bench_grouped_tts.py --limit 30 # cap lines (power-cut friendly)
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager
from tts_engine import TTSEngine, _normalize_text

DB_PATH = ROOT / "src" / "data" / "pipeline.db"
TTS_DIR = ROOT / "index-tts" / "checkpoints"


def _pick_chapter(sm: StateManager, chapter_id: "int | None") -> int:
    """Use the given chapter, or auto-pick the most speaker-interleaved one."""
    if chapter_id is not None:
        return chapter_id
    best, best_switches = None, -1
    for proj in sm.list_projects():
        for ch in sm.get_all_chapters(proj["id"]):
            lines = sm.get_lines_for_chapter(ch["id"])
            if len(lines) < 10:
                continue
            switches = sum(1 for i in range(1, len(lines))
                           if lines[i]["speaker"] != lines[i - 1]["speaker"])
            if switches > best_switches:
                best, best_switches = ch["id"], switches
    if best is None:
        print("[bench] No chapter with >=10 diarized lines found.", file=sys.stderr)
        sys.exit(2)
    print(f"[bench] Auto-picked chapter id={best} ({best_switches} speaker switches).")
    return best


def _prep(engine: TTSEngine, lines: list, voice_map: dict) -> list:
    """Resolve (text, ref, emo_vector, emo_alpha) per line; drop unmappable ones."""
    prepped = []
    for ln in lines:
        ref = engine._resolve_ref_audio(ln["speaker"], ln["emotion"], voice_map)
        if ref is None:
            continue
        emo_vector, emo_alpha = engine._resolve_emotion(ln["emotion"])
        emo_alpha *= engine.cfg["emo_alpha_scale"]
        prepped.append({
            "line_index": ln["line_index"],
            "text": _normalize_text(ln["text"]),
            "ref": ref, "emo_vector": emo_vector, "emo_alpha": emo_alpha,
        })
    return prepped


def _time_order(engine: TTSEngine, items: list, label: str) -> float:
    t0 = time.time()
    for it in items:
        engine._synthesize(it["text"], it["ref"], it["emo_vector"], it["emo_alpha"])
    elapsed = time.time() - t0
    print(f"[bench] {label:<14} {len(items)} lines in {elapsed:7.1f}s "
          f"({elapsed / max(1, len(items)):.2f}s/line)")
    return elapsed


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark speaker-grouped TTS.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--model-dir", default=str(TTS_DIR))
    ap.add_argument("--chapter", type=int, default=None)
    ap.add_argument("--limit", type=int, default=40, help="max lines to synthesise")
    args = ap.parse_args()

    sm = StateManager(args.db)
    chapter_id = _pick_chapter(sm, args.chapter)
    lines = sm.get_lines_for_chapter(chapter_id)
    voice_map = sm.get_voice_map()

    with TTSEngine(sm, str(ROOT / "data" / "_bench_audio"),
                   model_dir=args.model_dir) as engine:
        items = _prep(engine, lines, voice_map)[: args.limit]
        if len(items) < 4:
            print("[bench] Too few mappable lines to benchmark.", file=sys.stderr)
            sys.exit(2)

        line_order = list(items)
        grouped = sorted(items, key=lambda it: (it["ref"], it["line_index"]))
        switches = sum(1 for i in range(1, len(line_order))
                       if line_order[i]["ref"] != line_order[i - 1]["ref"])

        print(f"\n[bench] chapter id={chapter_id}, {len(items)} lines, "
              f"{switches} ref switches in line order.\n")

        # Warm the model (first-ever call pays one-time CUDA init) so it doesn't
        # bias whichever order runs first.
        engine._synthesize(items[0]["text"], items[0]["ref"],
                           items[0]["emo_vector"], items[0]["emo_alpha"])

        t_line = _time_order(engine, line_order, "line-order")
        t_group = _time_order(engine, grouped, "grouped")

    print("\n" + "=" * 56)
    if t_group > 0:
        print(f"  Speaker-grouped synthesis: {t_line / t_group:.2f}x "
              f"({t_line - t_group:+.1f}s on {len(items)} lines)")
    print("  Bigger win on more dialogue-interleaved chapters. Output audio is")
    print("  identical either way — this only changes conditioning recomputes.")
    print("=" * 56)


if __name__ == "__main__":
    main()
