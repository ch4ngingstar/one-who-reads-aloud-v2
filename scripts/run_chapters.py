"""
Run the full pipeline on a specific chapter index range.
Usage: python scripts/run_chapters.py <start_index> <end_index>
"""
import sys
import os
import time

# Run from src/ so relative DB paths resolve correctly
SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, os.path.abspath(SRC))
os.chdir(os.path.abspath(SRC))

from orchestrator import PipelineOrchestrator, PipelineConfig

ROOT  = os.path.abspath(os.path.join(SRC, ".."))
# Qwen2.5-14B Q4_K_M — single file (~8.5 GB VRAM), fits RTX 4070 sequentially with Fish Speech.
# Download: huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
#   → qwen2.5-14b-instruct-q4_k_m.gguf  (~8.5 GB)
MODEL = os.path.join(ROOT, "models", "qwen2.5-14b-instruct-q4_k_m.gguf")
# IndexTTS2 checkpoints dir (config.yaml + weights).
# Download: hf download IndexTeam/IndexTTS-2 --local-dir index-tts/checkpoints
TTS_MODEL_DIR = os.path.join(ROOT, "index-tts", "checkpoints")
EPUB  = "9kafe.com-shadow-slave-vol9-c1841-c2260.epub"

start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 2
end_idx   = int(sys.argv[2]) if len(sys.argv) > 2 else start_idx


def on_progress(event):
    t = event.get("type", "")
    if t in ("chapter_start", "stage_start", "stage_done",
             "chapter_done", "chapter_error", "chapter_skip",
             "pipeline_done", "tts_progress", "vram_warning"):
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {event}", flush=True)


config = PipelineConfig(
    epub_path       = EPUB,
    llm_model_path  = MODEL,
    tts_model_dir   = TTS_MODEL_DIR,
    db_path         = "data/pipeline.db",
    audio_wav_dir   = "data/audio",
    audio_mp3_dir   = "data/output",
    chapter_range   = (start_idx, end_idx),
)

print(f"Starting pipeline for chapter_index {start_idx}..{end_idx}", flush=True)
orch    = PipelineOrchestrator(config, progress_callback=on_progress)
results = orch.run()
print(f"Done: {results}", flush=True)
