"""Speech backends produce audio only; chapter scheduling and storage live elsewhere."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from fish_provider import FishProvider, is_fish
from reference_text import ReferenceTranscripts
from state_manager import _resolve_stored_path
from tts_engine import TTSEngine
from speech_audio import wav_silence

ROOT = Path(__file__).resolve().parents[1]
OMNI_HOME = ROOT / "models/omnivoice-runtime"
OMNI_PYTHON = OMNI_HOME / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
# OmniVoice warns that references over 20 s degrade cloning; longer clips get a cached
# copy cut at a sentence end (the registered file is never modified).
OMNI_MAX_REFERENCE_S = 20.0


def is_omni(directory):
    config = directory / "config.json"
    return config.is_file() and json.loads(config.read_text(encoding="utf-8")).get("model_type") == "omnivoice"


def provider_for(sm, directory, wav_root):
    directory = _resolve_stored_path(directory).resolve()
    if is_omni(directory):
        return OmniProvider(directory, wav_root)
    if is_fish(directory):
        return FishProvider(directory, wav_root)
    return IndexProvider(sm, directory, wav_root)


class IndexProvider:
    batch_size = 1

    def __init__(self, sm, directory, wav_root):
        self.engine = TTSEngine(sm, wav_root, model_dir=directory)
        self.directory = directory
        self.name = "IndexTTS 2.5" if (directory / "codec.pth").exists() else "IndexTTS 2"
        self.identity = checkpoint_identity(directory, self.name, ("*.pth", "*.model", "config.yaml"))
        self.identity = [self.identity, dict(self.engine.cfg),
                         file_digest(Path(__file__).with_name("index25_worker.py")),
                         file_digest(Path(__file__).with_name("tts_engine.py"))]

    def __enter__(self):
        self.engine.__enter__()
        return self

    def __exit__(self, *args):
        return self.engine.__exit__(*args)

    def render(self, requests):
        out = []
        for cue, text in requests:
            vec, alpha = self.engine._resolve_emotion(cue.emotion)
            if cue.actor == "Narrator":
                alpha *= self.engine.cfg["narrator_emo_scale"]
            out.append(self.engine._synthesize(text, cue.reference, vec, alpha))
        return out

    def pause(self):
        return wav_silence(250, 22050)


def checkpoint_identity(directory, name, patterns):
    # No multi-GB reads on startup. Size + replacement timestamp detect local changes.
    files = sorted({p for pattern in patterns for p in directory.glob(pattern) if p.is_file()})
    return [name, str(directory), [(p.relative_to(directory).as_posix(), p.stat().st_size,
                                    p.stat().st_mtime_ns) for p in files]]


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class OmniProvider:
    name = "OmniVoice"
    batch_size = 4

    def __init__(self, directory, wav_root):
        self.directory = directory
        self.identity = checkpoint_identity(directory, "OmniVoice 0.2.1 / 32 steps / v1",
                                            ("*.json", "*.safetensors", "audio_tokenizer/*"))
        self.identity = [self.identity, file_digest(Path(__file__).with_name("omni_worker.py"))]
        self.transcripts = ReferenceTranscripts(Path(wav_root) / ".reference-text")
        self.proc = None

    def __enter__(self):
        if not OMNI_PYTHON.exists():
            raise RuntimeError("Install OmniVoice with scripts/setup_omnivoice.ps1 first.")
        self.proc = subprocess.Popen([str(OMNI_PYTHON), str(Path(__file__).with_name("omni_worker.py")),
                                      str(self.directory)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, encoding="utf-8",
                                     env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"})
        try:
            self._receive()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _receive(self):
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"OmniVoice process exited ({self.proc.poll()}); see backend log.")
        error = json.loads(line).get("error")
        if error:
            raise RuntimeError(error)

    def __exit__(self, *args):
        self.proc.stdin.close()
        try:
            self.proc.wait(6)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()
        self.transcripts.close()

    def reference(self, cue):
        return self.transcripts.fitted(cue.reference, cue.reference_hash, cue.actor, OMNI_MAX_REFERENCE_S)

    def transcript(self, cue):
        return self.reference(cue)[1]

    def conditioning_identity(self, cue):
        return [self.identity, self.transcript(cue)]

    def render(self, requests):
        with tempfile.TemporaryDirectory() as tmp:
            items = [{"ref_hash": cue.reference_hash, "reference": self.reference(cue)[0],
                      "ref_text": self.transcript(cue), "text": text,
                      "out": str(Path(tmp) / f"{i}.wav")} for i, (cue, text) in enumerate(requests)]
            self.proc.stdin.write(json.dumps(items) + "\n")
            self.proc.stdin.flush()
            self._receive()
            return [Path(item["out"]).read_bytes() for item in items]

    def pause(self):
        return wav_silence(250, 24000)
