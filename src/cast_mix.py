"""Set one dialogue level per actor, preserving the dynamics between their lines."""

from collections import defaultdict
import math
from pathlib import Path
from statistics import median
import wave

import numpy as np

from state_manager import _resolve_stored_path


def _samples(line):
    with wave.open(str(_resolve_stored_path(line["audio_path"])), "rb") as source:
        params = source.getparams()
        pcm = np.frombuffer(source.readframes(params.nframes), dtype="<i2")
    return params, pcm.astype(np.float64) / 32768


def balance_cast(lines, cues, folder: Path, target=-20.0):
    import pyloudnorm as pyln

    by_index = {cue["index"]: cue for cue in cues}
    levels, ordinary = defaultdict(list), defaultdict(list)
    meters = {}
    for line in lines:
        cue = by_index[line["line_index"]]
        params, samples = _samples(line)
        if params.nchannels != 1 or params.sampwidth != 2:
            raise ValueError("Cast mix requires mono 16-bit takes.")
        if params.framerate not in meters:
            meters[params.framerate] = pyln.Meter(params.framerate)
        if len(samples) < math.ceil(.4 * params.framerate):
            continue
        level = meters[params.framerate].integrated_loudness(samples)
        if math.isfinite(level):
            actor = cue["actor"]
            levels[actor].append(level)
            if cue["emotion"] in {"neutral", "confused", "cold", "sarcastic"}:
                ordinary[actor].append(level)
    gains = {actor: float(np.clip(target - median(ordinary[actor] or values), -9, 9))
             for actor, values in levels.items()}
    mixed = []
    for line in lines:
        cue = by_index[line["line_index"]]
        params, samples = _samples(line)
        gain = gains.get(cue["actor"], 0.0)
        if not ordinary[cue["actor"]] and cue["emotion"] == "whispers":
            gain = min(gain, 0.0)
        peak = float(np.max(np.abs(samples), initial=0))
        if peak:
            gain = min(gain, -1.5 - 20 * math.log10(peak))
        cue["mix_gain_db"] = round(gain, 2)
        dest = folder / f"mix_{line['line_index']:05d}.wav"
        with wave.open(str(dest), "wb") as target_wav:
            target_wav.setparams(params)
            target_wav.writeframes(np.rint(samples * (32768 * 10**(gain / 20))).astype("<i2").tobytes())
        mixed.append({**line, "audio_path": str(dest)})
    return mixed, {actor: round(gain, 2) for actor, gain in gains.items()}
