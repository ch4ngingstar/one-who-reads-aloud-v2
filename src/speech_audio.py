"""Checks for unusable speech that model inference can return without an exception."""

import io
from math import gcd
import wave

import numpy as np


def studio_pcm(audio: bytes) -> bytes:
    """Bring every actor onto the same 24 kHz mono timeline before concatenation."""
    with wave.open(io.BytesIO(audio), "rb") as source:
        rate, channels = source.getframerate(), source.getnchannels()
        if source.getsampwidth() != 2:
            raise ValueError("Renderer must supply 16-bit PCM")
        if rate == 24000 and channels == 1:
            return audio
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    from scipy.signal import resample_poly
    samples = pcm.reshape(-1, channels).mean(axis=1)
    if rate != 24000:
        divisor = gcd(rate, 24000)
        samples = resample_poly(samples, 24000 // divisor, rate // divisor)
    result = io.BytesIO()
    with wave.open(result, "wb") as out:
        out.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        out.writeframes(np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes())
    return result.getvalue()


def tighten_edges(audio: bytes, lead_ms: int = 30, tail_ms: int = 60, below_peak_db: float = 40.0,
                  floor_db: float = -55.0, fade_ms: int = 5) -> bytes:
    """Give a take the same small edge padding whichever engine recorded it.

    OmniVoice opens a take with ~200 ms of silence (up to 660 ms) and Fish with none,
    so fixed gaps between raw takes made pacing depend on who was speaking. Only the
    edges are trimmed — pauses inside the take are kept — and a short fade keeps the
    cut silent. The voiced threshold is relative to the take's own peak, so quiet
    whispers keep their soft onsets.
    """
    with wave.open(io.BytesIO(audio), "rb") as source:
        params = source.getparams()
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    if params.nchannels != 1 or params.sampwidth != 2:
        return audio
    rate = params.framerate
    window = max(1, rate // 100)
    frames = len(pcm) // window
    if frames == 0:
        return audio
    signal = pcm[:frames * window].astype(np.float64).reshape(frames, window) / 32768
    level = 20 * np.log10(np.sqrt(np.mean(signal ** 2, axis=1)) + 1e-12)
    voiced = np.flatnonzero(level > max(floor_db, level.max() - below_peak_db))
    if voiced.size == 0:
        return audio
    start = max(0, voiced[0] * window - lead_ms * rate // 1000)
    end = min(len(pcm), (voiced[-1] + 1) * window + tail_ms * rate // 1000)
    if start == 0 and end == len(pcm):
        return audio
    kept = pcm[start:end].astype(np.float64)
    fade = min(len(kept) // 2, fade_ms * rate // 1000)
    if fade:
        if start > 0:
            kept[:fade] *= np.linspace(0.0, 1.0, fade)
        if end < len(pcm):
            kept[-fade:] *= np.linspace(1.0, 0.0, fade)
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setparams(params)
        target.writeframes(np.clip(np.rint(kept), -32768, 32767).astype("<i2").tobytes())
    return out.getvalue()


def check_pcm(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as source:
        frames = source.getnframes()
        channels = source.getnchannels()
        if source.getsampwidth() != 2:
            raise ValueError("Expected 16-bit PCM audio")
        samples = np.frombuffer(source.readframes(frames), dtype="<i2")
        if not frames or samples.size != frames * channels:
            raise ValueError("Empty or truncated WAV")
        if not np.any((samples > 32) | (samples < -32)):
            raise ValueError("The recording contains no audible signal")
        return frames / source.getframerate()


def check_utterance(audio: bytes, text: str) -> None:
    duration = check_pcm(audio)
    words = len(text.split())
    # Leave room for whispers, slow dramatic reads and fast dialogue. These
    # limits catch severe truncation and decoder runaways, not acting choices.
    if duration < max(0.10, (words - 3) / 8) or duration > max(14, words * 1.6 + 5):
        raise ValueError(f"Unexpected speech duration ({duration:.1f}s for {words} words)")


def wav_silence(duration_ms: int = 100, sample_rate: int = 22050) -> bytes:
    """Generate a minimal silent WAV file as a fallback placeholder."""
    import struct
    n_samples = int(sample_rate * duration_ms / 1000)
    data = b"\x00\x00" * n_samples  # 16-bit silence
    data_size = len(data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16,
        1,                    # PCM
        1,                    # mono
        sample_rate,
        sample_rate * 2,      # byte rate
        2,                    # block align
        16,                   # bits per sample
        b"data", data_size,
    )
    return header + data


def concat_wavs(wav_list: list) -> bytes:
    """Concatenate multiple WAV byte strings into a single WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        for i, raw in enumerate(wav_list):
            with wave.open(io.BytesIO(raw), "rb") as src:
                if i == 0:
                    out.setparams(src.getparams())
                out.writeframes(src.readframes(src.getnframes()))
    return buf.getvalue()

