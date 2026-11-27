"""Sample total GPU 0 memory during local benchmarks, including desktop applications."""

import subprocess
import threading


class GpuMemory:
    def __init__(self):
        self.baseline = None
        self.peak = None
        self._stop = threading.Event()

    def _sample(self):
        try:
            result = subprocess.run(
                ["nvidia-smi", "-i", "0", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=True,
            )
            return int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _poll(self):
        while not self._stop.wait(0.5):
            value = self._sample()
            if value is not None:
                self.peak = max(self.peak, value)

    def __enter__(self):
        self.baseline = self.peak = self._sample()
        self._thread = None
        if self.baseline is not None:
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop.set()
        if self._thread:
            self._thread.join()

    def report(self):
        return {"gpu0_baseline_mib": self.baseline, "gpu0_sampled_peak_mib": self.peak}
