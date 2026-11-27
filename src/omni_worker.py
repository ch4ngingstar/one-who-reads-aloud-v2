"""Private offline process for OmniVoice; one model and one prompt per cast reference."""

import json
import os
from pathlib import Path
import sys


def main():
    with os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1) as replies:
        os.dup2(2, 1)
        try:
            import soundfile as sf
            import torch
            from omnivoice import OmniVoice
            if not torch.cuda.is_available():
                raise RuntimeError("This renderer requires CUDA-enabled PyTorch.")
            model = OmniVoice.from_pretrained(sys.argv[1], device_map="cuda:0", dtype=torch.float16)
            prompts = {}
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), file=replies, flush=True)
            raise
        print("{}", file=replies, flush=True)
        for message in sys.stdin:
            try:
                items = json.loads(message)
                with torch.inference_mode():
                    for item in items:
                        key = item["ref_hash"]
                        if key not in prompts:
                            audio, sr = sf.read(item["reference"], dtype="float32", always_2d=True)
                            prompts[key] = model.create_voice_clone_prompt(
                                ref_audio=(torch.from_numpy(audio.mean(axis=1)).unsqueeze(0), sr),
                                ref_text=item["ref_text"],
                            )
                    audio = model.generate(text=[i["text"] for i in items],
                                           language=["English"] * len(items),
                                           voice_clone_prompt=[prompts[i["ref_hash"]] for i in items],
                                           num_step=32)
                    if len(audio) != len(items):
                        raise ValueError("Renderer returned a different number of takes than requested")
                    for out, item in zip(audio, items):
                        sf.write(item["out"], out, 24000, subtype="PCM_16")
                print("{}", file=replies, flush=True)
            except Exception as exc:
                torch.cuda.empty_cache()
                print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=replies, flush=True)


if __name__ == "__main__":
    main()
