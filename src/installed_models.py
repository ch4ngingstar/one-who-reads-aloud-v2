"""Shared model discovery for the studio and command-line renderer."""

import os
import json
from pathlib import Path


def installed_models(root: Path):
    omni_home = root / "models/omnivoice-runtime"
    python = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
    choices = []
    omni = omni_home / "checkpoints"
    if (omni_home / python).is_file() and all((omni / name).is_file() for name in (
            "model.safetensors", "audio_tokenizer/model.safetensors", "config.json")):
        choices.append({"name": "OmniVoice · batched cast", "path": str(omni)})
    fish = root / "models/audio-cpp/Fish-Audio-S2-Pro-GGUF"
    server = root / "models/audio-runtime" / ("audiocpp_server.exe" if os.name == "nt" else "audiocpp_server")
    if server.is_file() and any(fish.glob("fish-audio-s2-pro*.gguf")):
        choices.append({"name": "Fish S2 Pro · audio.cpp server", "path": str(fish)})
    for name, folder, extra in [
        ("IndexTTS 2.5", "models/indextts25-runtime/checkpoints", "codec.pth"),
        ("IndexTTS 2", "index-tts/checkpoints", "bpe.model"),
    ]:
        path = root / folder
        if all((path / file).is_file() for file in ["config.yaml", "gpt.pth", "s2mel.pth", extra]):
            choices.append({"name": name, "path": str(path)})
    profile = root / "profiles/full-cast.json"
    installed = {Path(c["path"]).resolve() for c in choices if Path(c["path"]).is_dir()}
    # The default cast profile goes first (the UI preselects the first choice).
    for path in sorted(profile.parent.glob("*.json"), key=lambda p: p != profile):
        try:
            cast = json.loads(path.read_text(encoding="utf-8"))
            routes = [cast["narrator"], cast["characters"], *cast.get("actors", {}).values()]
            if all((root / route).resolve() in installed for route in routes):
                entry = {"name": str(cast.get("name") or path.stem), "path": str(path)}
                if path == profile:
                    choices.insert(0, entry)
                else:
                    choices.append(entry)
        except (AttributeError, KeyError, OSError, TypeError, ValueError):
            continue
    ggufs = sorted((root / "models").glob("*.gguf"))
    directors = [p for p in ggufs if "-of-" not in p.name or "-00001-of-" in p.name]
    directors.sort(key=lambda p: not p.name.lower().startswith("qwen3"))
    return {"tts": choices, "llm": [str(p) for p in directors]}
