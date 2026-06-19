"""Measure the per-chapter VRAM swap tax that stage-batching is meant to remove.

The June 2026 council's premise: the dominant waste in the old chapter-at-a-time
loop is loading the LLM + crossing the VRAM barrier + loading IndexTTS2 *once per
chapter*. This script times those three components ONCE, faithfully (same context
managers the orchestrator uses), without synthesizing a whole chapter — so it runs
in minutes and is friendly to a power-cut-prone machine.

Compare the printed total against a real chapter's processing_seconds (already in
pipeline.db) to decide whether batch_size is worth the power-cut risk.

Run from repo root:  python scripts/measure_swap_tax.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from state_manager import StateManager
from llm_director import LLMDirector
from tts_engine import TTSEngine
from orchestrator import _query_vram_used_mb

LLM_PATH  = ROOT / "models" / "Qwen3-14B-Q4_K_M.gguf"
TTS_DIR   = ROOT / "index-tts" / "checkpoints"
DB_PATH   = ROOT / "src" / "data" / "pipeline.db"
WAV_DIR   = ROOT / "data" / "audio"

BARRIER_DELTA_MB = 1024   # "back to baseline" threshold the orchestrator uses (~1GB)
BARRIER_TIMEOUT  = 180    # matches the reliability fix


def vram() -> int:
    mb = _query_vram_used_mb()
    return mb if mb >= 0 else 0


def main() -> None:
    sm = StateManager(str(DB_PATH))

    baseline = vram()
    print(f"[measure] VRAM baseline (desktop apps): {baseline} MB\n")

    # ── 1. LLM cold load + unload ────────────────────────────────────────────
    t0 = time.time()
    with LLMDirector(str(LLM_PATH), sm, cfg={"n_gpu_layers": -1}):
        llm_load = time.time() - t0
        print(f"[measure] LLM loaded:        {llm_load:6.1f}s  "
              f"(VRAM now {vram()} MB)")
    llm_total = time.time() - t0   # includes __exit__ unload

    # ── 2. VRAM barrier: wait until the LLM's memory is actually released ─────
    t0 = time.time()
    while time.time() - t0 < BARRIER_TIMEOUT:
        if vram() - baseline < BARRIER_DELTA_MB:
            break
        time.sleep(1)
    barrier = time.time() - t0
    print(f"[measure] VRAM barrier:      {barrier:6.1f}s  "
          f"(VRAM back to {vram()} MB)")

    # ── 3. TTS (IndexTTS2) cold load + unload ────────────────────────────────
    t0 = time.time()
    with TTSEngine(sm, str(WAV_DIR), model_dir=str(TTS_DIR)):
        tts_load = time.time() - t0
        print(f"[measure] IndexTTS2 loaded:  {tts_load:6.1f}s  "
              f"(VRAM now {vram()} MB)")

    # ── Verdict ──────────────────────────────────────────────────────────────
    swap_tax = llm_total + barrier + tts_load
    print("\n" + "=" * 56)
    print(f"  PER-CHAPTER SWAP TAX (old loop) ~ {swap_tax:6.1f}s")
    print(f"    LLM load+unload : {llm_total:6.1f}s")
    print(f"    VRAM barrier    : {barrier:6.1f}s")
    print(f"    TTS load        : {tts_load:6.1f}s")
    print("=" * 56)
    print("  Compare vs a real chapter's processing_seconds in pipeline.db")
    print("  (project 2 chapters ran ~234-753s each). If swap_tax is a large")  # noqa
    print("  fraction of that, batching pays off; if small, batch_size mostly")
    print("  just adds power-cut risk.")


if __name__ == "__main__":
    main()
