"""Persistent IndexTTS 2.5 worker. Its dependencies stay outside the API process."""

import json
import os
from pathlib import Path
import subprocess
import sys


RUNTIME = Path(__file__).resolve().parents[1] / "models" / "indextts25-runtime"


class Index25Worker:
    def __init__(self, model_dir: Path):
        venv_python = RUNTIME / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not (RUNTIME / "indextts/infer_v2_5.py").is_file():
            raise RuntimeError("IndexTTS 2.5 runtime missing. See the IndexTTS 2.5 setup in README.md.")
        self.proc = subprocess.Popen(
            [str(venv_python if venv_python.is_file() else sys.executable),
             str(Path(__file__).resolve()), str(model_dir)],
            cwd=RUNTIME, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        try:
            self._receive()
        except BaseException:
            self.close()
            raise

    def _receive(self):
        reply = self.proc.stdout.readline()
        if not reply:
            raise RuntimeError(f"IndexTTS 2.5 worker exited (code {self.proc.poll()}). See backend log.")
        error = json.loads(reply).get("error")
        if error:
            raise RuntimeError(error)

    def infer(self, **kwargs):
        kwargs["spk_audio_prompt"] = str(Path(kwargs["spk_audio_prompt"]).resolve())
        self.proc.stdin.write(json.dumps(kwargs) + "\n")
        self.proc.stdin.flush()
        self._receive()

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        finally:
            self.proc.stdout.close()


def main():
    # Third-party libraries (including native code) print to stdout. Reserve
    # the original pipe for replies and send all model diagnostics to stderr.
    with os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1) as replies:
        os.dup2(2, 1)
        def reply(error=None):
            print(json.dumps({"error": error}), file=replies, flush=True)

        sys.path.insert(0, str(RUNTIME))
        try:
            import torch
            from indextts.infer_v2_5 import IndexTTS2

            directory = Path(sys.argv[1])
            model = IndexTTS2(cfg_path=str(directory / "config.yaml"), model_dir=str(directory),
                              use_bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
                              use_cuda_kernel=False)
        except Exception as exc:
            reply(f"IndexTTS 2.5 startup failed: {type(exc).__name__}: {exc}")
            raise
        reply()
        for line in sys.stdin:
            try:
                model.infer(lang="EN", **json.loads(line))
            except Exception as exc:
                reply(f"{type(exc).__name__}: {exc}")
            else:
                reply()


if __name__ == "__main__":
    main()
