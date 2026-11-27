"""Fish Audio S2 Pro through a long-lived local audio.cpp server.

The model loads once per recording session (~30 s) and then renders a line in ~2 s,
instead of paying the full load for every line as a per-call CLI would. Each line's
emotion label becomes an inline Fish [bracket] delivery cue (profiles/fish-direction.json).
"""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from process_guard import contain
from reference_text import ReferenceTranscripts
from speech_audio import wav_silence

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "models/audio-runtime" / ("audiocpp_server.exe" if os.name == "nt" else "audiocpp_server")
DIRECTION = ROOT / "profiles/fish-direction.json"
WEIGHTS_GLOB = "fish-audio-s2-pro*.gguf"
LOAD_TIMEOUT_S = 600
REQUEST_TIMEOUT_S = 300
# Bump when a change alters the audio rendered for identical inputs (request fields, seeds,
# reference handling); it is part of every take key, so cached takes re-record exactly then.
RENDER_VERSION = 2
# Speakers alternate within a scene; keep every recent cast reference encoded.
REFERENCE_CACHE_SLOTS = 16
# Encoding a 30 s reference needs a 5.8 GB codec graph (out of memory on 12 GB);
# 21.6 s was measured to fit, so references are trimmed at a sentence end below this.
MAX_REFERENCE_S = 18.0


def is_fish(directory: Path) -> bool:
    return directory.is_dir() and any(directory.glob(WEIGHTS_GLOB))


def load_direction(path=DIRECTION) -> dict:
    try:
        cues = json.loads(Path(path).read_text(encoding="utf-8"))["cues"]
    except FileNotFoundError:
        return {}
    if not isinstance(cues, dict) or not all(isinstance(v, str) for v in cues.values()):
        raise ValueError(f"{path}: 'cues' must map emotion names to strings")
    return {k.casefold(): v.strip() for k, v in cues.items()}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FishProvider:
    name = "Fish S2 Pro"
    # audio.cpp serialises requests per model, so larger batches would not run faster.
    batch_size = 1

    def __init__(self, directory, wav_root, direction=None):
        self.directory = Path(directory)
        weights = sorted(self.directory.glob(WEIGHTS_GLOB))
        if not weights:
            raise RuntimeError(f"No Fish S2 Pro weights ({WEIGHTS_GLOB}) in {self.directory}")
        # Prefer the 8-bit file: BF16 does not fit a 12 GB card next to the codec.
        self.weights = next((w for w in weights if "q8" in w.name.lower()), weights[0])
        stat = self.weights.stat()
        self.identity = ["Fish S2 Pro / audio.cpp", RENDER_VERSION, self.weights.name, stat.st_size,
                         stat.st_mtime_ns]
        self.direction = load_direction() if direction is None else direction
        self.transcripts = ReferenceTranscripts(Path(wav_root) / ".reference-text")
        self.log_path = Path(wav_root) / ".fish-server.log"
        self.proc = None
        self.guard = None
        self.url = None
        self.workdir = None
        self.attempts = {}
        # {actor: {emotion}}: labels so common for a character that they are his normal
        # voice, not a mood (Nephis was labelled 'commanding' on 64% of her lines).
        self.baselines = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def __enter__(self):
        if not SERVER.is_file():
            raise RuntimeError(f"audio.cpp server not found at {SERVER}")
        self.workdir = tempfile.TemporaryDirectory(prefix="fish-server-")
        config = Path(self.workdir.name) / "server.json"
        config.write_text(json.dumps({"models": [{
            "id": "fish", "family": "fish_audio", "path": str(self.weights),
            "session_options": {"reference_cache_slots": REFERENCE_CACHE_SLOTS},
        }]}), encoding="utf-8")
        port = free_port()
        self.url = f"http://127.0.0.1:{port}"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(
                [str(SERVER), "--config", str(config), "--backend", "vulkan", "--port", str(port),
                 "--no-ui", "--max-loaded-models", "1", "--log"],
                stdout=log, stderr=subprocess.STDOUT, cwd=SERVER.parent)
        finally:
            log.close()
        self.guard = contain(self.proc)
        try:
            self._wait_until_loaded()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _wait_until_loaded(self):
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Fish server exited ({self.proc.returncode}): {self._log_tail()}")
            try:
                with urllib.request.urlopen(self.url + "/v1/models", timeout=5) as reply:
                    models = json.loads(reply.read())["data"]
                if any(m["id"] == "fish" and m.get("loaded") for m in models):
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, KeyError):
                pass
            time.sleep(1)
        raise RuntimeError(f"Fish server did not load within {LOAD_TIMEOUT_S}s: {self._log_tail()}")

    def _log_tail(self, lines=8):
        try:
            return " | ".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return "(no server log)"

    def __exit__(self, *args):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None
        if self.guard is not None:
            self.guard.close()
            self.guard = None
        if self.workdir is not None:
            self.workdir.cleanup()
            self.workdir = None
        self.transcripts.close()

    # ── direction and conditioning ─────────────────────────────────────────────
    def cue_for(self, cue) -> str:
        # The narrator stays plain: directed narration was the over-acting fixed in June.
        if cue.actor == "Narrator" or cue.emotion.casefold() in self.baselines.get(cue.actor, ()):
            return ""
        return self.direction.get(cue.emotion.casefold(), "")

    def directed(self, cue, text) -> str:
        tag = self.cue_for(cue)
        return f"{tag} {text}" if tag else text

    def reference(self, cue):
        return self.transcripts.fitted(cue.reference, cue.reference_hash, cue.actor, MAX_REFERENCE_S)

    def transcript(self, cue):
        return self.reference(cue)[1]

    def conditioning_identity(self, cue):
        # Only this line's own cue is part of its take key, so editing one emotion's
        # cue re-records just the lines carrying that emotion.
        return [self.identity, self.transcript(cue), self.cue_for(cue)]

    def seed(self, cue, text):
        # Deterministic first take (stable cache), a fresh draw for every retake.
        key = (cue.line_id, cue.index, text)
        attempt = self.attempts.get(key, 0)
        self.attempts[key] = attempt + 1
        base = int(hashlib.sha256(f"{cue.reference_hash}|{text}".encode()).hexdigest()[:8], 16)
        return (base + attempt * 7919) % 2**31

    # ── rendering ──────────────────────────────────────────────────────────────
    def render(self, requests):
        if self.proc is None:
            raise RuntimeError("Fish provider used outside its recording session")
        return [self._speak(cue, text) for cue, text in requests]

    def _speak(self, cue, text):
        reference, words = self.reference(cue)
        body = {"model": "fish", "input": self.directed(cue, text),
                "voice_ref": {"type": "path", "path": reference},
                "reference_text": words, "seed": self.seed(cue, text),
                "response_format": "wav"}
        request = urllib.request.Request(self.url + "/v1/audio/speech", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as reply:
                audio = reply.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(f"Fish server rejected {cue.actor}'s line: {exc.code} {detail}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise RuntimeError(f"Fish server unreachable: {exc}; {self._log_tail()}") from exc
        if audio[:4] != b"RIFF":
            raise RuntimeError(f"Fish server returned non-WAV audio for {cue.actor}'s line")
        return audio

    def pause(self):
        return wav_silence(250, 24000)
