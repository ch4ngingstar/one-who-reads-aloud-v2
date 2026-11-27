"""Design clean cloning references from novel-derived voice briefs with Qwen3-TTS VoiceDesign.

Run with the isolated runtime (its transformers pin conflicts with the other engines):
    models/qwen3-tts-runtime/.venv/Scripts/python.exe scripts/design_voices.py [--only Sunny Nephis]

Each candidate is written to data/voice-design/<character>/cand_<n>.wav with a JSON sidecar.
Existing candidates are kept, so an interrupted run (power cut) resumes where it stopped.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BRIEFS = ROOT / "profiles/voice-briefs.json"
MODEL = ROOT / "models/qwen3-tts-voicedesign"
OUT = ROOT / "data/voice-design"
MODEL_REVISION = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign@5ecdb67327fd37bb2e042aab12ff7391903235d3"
BASE_SEED = 1000


def slug(name):
    return name.lower().replace(" ", "_")


def load_briefs(only):
    briefs = json.loads(BRIEFS.read_text(encoding="utf-8"))
    cast = briefs["characters"]
    unknown = sorted(set(only or []) - set(cast))
    if unknown:
        raise SystemExit(f"No brief for: {', '.join(unknown)}")
    selected = {name: cast[name] for name in (only or cast)}
    for name, brief in selected.items():
        for key in ("instruct", "reference_script", "candidates"):
            if not brief.get(key):
                raise SystemExit(f"Brief for {name} is missing '{key}'")
    return briefs["recording"], selected


def write_candidate(path, audio, sample_rate, record):
    import soundfile as sf

    peak = float(abs(audio).max()) if audio.size else 0.0
    if audio.size == 0 or peak < 1e-3:
        raise RuntimeError(f"Silent output for {path.name}")
    # Normalise peaks only; loudness matching happens later in the mix.
    audio = audio * min(1.0, 0.89 / peak)
    tmp = path.with_suffix(".tmp.wav")
    sf.write(tmp, audio, sample_rate, subtype="PCM_16")
    os.replace(tmp, path)
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record["duration_s"] = round(len(audio) / sample_rate, 2)
    path.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", help="Characters to design (default: every brief)")
    parser.add_argument("--extra", type=int, default=0, help="Add this many candidates beyond the brief's count")
    args = parser.parse_args()
    recording, cast = load_briefs(args.only)
    if not (MODEL / "model.safetensors").is_file():
        raise SystemExit(f"VoiceDesign weights not found in {MODEL}")

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import torch
    from qwen_tts import Qwen3TTSModel

    if not torch.cuda.is_available():
        raise SystemExit("VoiceDesign needs CUDA-enabled PyTorch")
    started = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16,
                                          attn_implementation="sdpa")
    print(f"Model loaded in {time.monotonic() - started:.1f}s", flush=True)

    for name, brief in cast.items():
        folder = OUT / slug(name)
        folder.mkdir(parents=True, exist_ok=True)
        # Variants explore different readings of the same character, one candidate each,
        # after the base brief's candidates (a later round never renumbers earlier picks).
        variants = brief.get("variants", [])
        for n in range(1, brief["candidates"] + len(variants) + args.extra + 1):
            variant = n - brief["candidates"] - 1
            described = variants[variant] if 0 <= variant < len(variants) else brief["instruct"]
            instruct = f"{described} {recording}"
            path = folder / f"cand_{n}.wav"
            if path.is_file() and path.with_suffix(".json").is_file():
                print(f"{name} #{n}: kept", flush=True)
                continue
            seed = BASE_SEED + n
            torch.manual_seed(seed)
            t0 = time.monotonic()
            wavs, sample_rate = model.generate_voice_design(
                text=brief["reference_script"], instruct=instruct, language="English",
                do_sample=True, max_new_tokens=2048,
            )
            write_candidate(path, wavs[0], sample_rate, {
                "character": name, "candidate": n, "seed": seed, "instruct": instruct,
                "reference_script": brief["reference_script"], "model_revision": MODEL_REVISION,
                "render_seconds": round(time.monotonic() - t0, 2),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            print(f"{name} #{n}: designed in {time.monotonic() - t0:.1f}s", flush=True)
    print(f"Done in {time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
