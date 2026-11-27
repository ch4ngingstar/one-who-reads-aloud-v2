"""Render matched plain-delivery voice reference pairs in an offline benchmark."""

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import wave

import numpy as np
from gpu_measurement import GpuMemory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from speech_audio import check_utterance, studio_pcm
from speech_providers import IndexProvider, file_digest
from take_review import TakeReviewer

BENCH = ROOT / "data/benchmarks"
DEFAULT_SHEET = BENCH / "ch-156-998055wm/ch_0001.performance.json"
VOICES = ROOT / "src/data/voices"
INDEX = ROOT / "models/indextts25-runtime/checkpoints"
MODEL_HOME = ROOT / "models/audio-cpp"
AUDIOCPP = {
    "higgs": ("higgs_audio_tts", MODEL_HOME / "Higgs-Audio-v3-TTS-4B-GGUF/higgs-audio-v3-tts-4b-q8_0.gguf"),
    "fish": ("fish_audio", MODEL_HOME / "Fish-Audio-S2-Pro-GGUF/fish-audio-s2-pro-q8_0.gguf"),
}
ENGINE_NAMES = {"index": "IndexTTS 2.5", "higgs": "Higgs TTS 3 Q8_0", "fish": "Fish S2 Pro Q8_0"}
CLI = ROOT / "models/audio-runtime/audiocpp_cli.exe"
CAST = {"Sunny": 63, "Nephis": 67, "Cassie": None}
CASSIE_TEXT = "No, not quite. It is far more profound than that."


def transcribe(asr, path):
    segments, _ = asr.transcribe(str(path), language="en", condition_on_previous_text=False)
    return " ".join(segment.text.strip() for segment in segments)


def normalized_wav(audio):
    with wave.open(io.BytesIO(audio)) as source:
        frames = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(float)
        params = source.getparams()
    rms = np.sqrt(np.mean(frames ** 2))
    gain = min(2500 / rms, 29000 / np.max(np.abs(frames)))
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setparams(params)
        output.writeframes(np.rint(frames * gain).astype("<i2").tobytes())
    return target.getvalue()


def manifest(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_comparisons(out):
    """Write a listening-pack manifest from completed, reviewed takes."""
    comparisons = []

    def add(actor, title, kind, paths, labels, pair=None):
        sides = []
        for path, label in zip(paths, labels):
            if not path.is_file() or not path.with_suffix(".json").is_file():
                return
            take = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            if "audit" not in take:
                return
            sides.append({**take, "label": label, "path": path.relative_to(out).as_posix()})
        if sides[0]["spoken"] != sides[1]["spoken"]:
            raise ValueError("A comparison requires identical spoken text")
        if kind == "line" and sides[0]["reference_sha256"] != sides[1]["reference_sha256"]:
            raise ValueError(f"The two {actor} engine takes use different references")
        if pair is not None:
            pair.mkdir(exist_ok=True)
            for side, path, take in zip(("current", "candidate"), paths, sides):
                output = pair / (side + ".wav")
                shutil.copyfile(path, output)
                shutil.copyfile(path.with_suffix(".json"), output.with_suffix(".json"))
                take["path"] = output.relative_to(out).as_posix()
        comparisons.append({"kind": kind, "roles": [actor], "title": title, "variants": sides})

    for actor in CAST:
        sources = {engine: out / (engine + "-" + actor.lower()) for engine in ENGINE_NAMES}
        if actor != "Cassie":
            for engine, source in sources.items():
                same_engine = [source / name for name in ("current.wav", "candidate.wav")]
                add(actor, "Reference comparison", "reference", same_engine,
                    [f"{ENGINE_NAMES[engine]}: current reference",
                     f"{ENGINE_NAMES[engine]}: alternate reference"])
        reference_sides = ("current", "candidate") if actor != "Cassie" else ("current",)
        for challenger in AUDIOCPP:
            for reference in reference_sides:
                pair_name = f"engine-{challenger}-{actor.lower()}"
                if actor != "Cassie":
                    pair_name += "-" + reference
                paths = [sources[engine] / (reference + ".wav") for engine in ("index", challenger)]
                variant = "alternate" if reference == "candidate" else "current"
                add(actor, "Engine comparison", "line", paths,
                    [f"{ENGINE_NAMES['index']}: {variant} reference",
                     f"{ENGINE_NAMES[challenger]}: {variant} reference"],
                    pair=out / pair_name)
    if comparisons:
        manifest(out / "comparisons.json", {"comparisons": comparisons})


def render(args, out, specs, gpu):
    index = None
    if args.engine == "index":
        index = IndexProvider(None, INDEX, out)
        model = INDEX
    else:
        family, model = AUDIOCPP[args.engine]
    run_start = time.monotonic()
    finished_seconds = 0.0
    reused_seconds = 0.0
    reused_scene = (json.loads((args.reuse_scene / "report.json").read_text(encoding="utf-8"))
                    if args.reuse_scene else [])
    try:
        model_start = time.monotonic()
        if index is not None:
            index.__enter__()
        model_load = time.monotonic() - model_start if index is not None else None
        for actor, variants in specs.items():
            pair = out / (args.engine + "-" + actor.lower())
            pair.mkdir()
            for label, cue, reference, spoken in variants:
                started = time.monotonic()
                seed = 42
                reference_hash = file_digest(reference)
                reference_text = args.transcripts[reference]
                reused = None
                if index is not None:
                    request = SimpleNamespace(actor=actor, emotion="neutral", reference=str(reference))
                    raw, = index.render([(request, spoken)])
                else:
                    expected = {
                        "index": cue, "speaker": actor, "family": family, "model": str(model),
                        "backend": args.backend, "seed": seed, "higgs_emotion": None,
                        "spoken": spoken, "reference_hash": reference_hash,
                        "reference_text": reference_text,
                    }
                    reused = next((line for line in reused_scene
                                   if all(key in line and line[key] == value
                                          for key, value in expected.items())), None)
                    if reused is not None:
                        raw = (args.reuse_scene / f"line_{cue}.wav").read_bytes()
                    else:
                        temp = pair / (label + ".raw.wav")
                        with (pair / (label + ".log")).open("wb") as log:
                            subprocess.run(
                                [str(CLI), "--task", "clon", "--family", family,
                                 "--model", str(model), "--backend", args.backend,
                                 "--text", spoken, "--voice-ref", str(reference),
                                 "--reference-text", reference_text, "--seed", str(seed),
                                 "--max-tokens", "512", "--out", str(temp)],
                                check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                            )
                        raw = temp.read_bytes()
                        temp.unlink()
                wall = reused["wall_s"] if reused is not None else time.monotonic() - started
                audio = studio_pcm(raw)
                check_utterance(audio, spoken)
                wav = pair / (label + ".wav")
                wav.write_bytes(normalized_wav(audio))
                with wave.open(str(wav)) as source:
                    duration = source.getnframes() / source.getframerate()
                if reused is None:
                    finished_seconds += duration
                else:
                    reused_seconds += duration
                manifest(pair / (label + ".json"), {
                    "actor": actor, "engine": index.name if index else ENGINE_NAMES[args.engine],
                    "model": str(model),
                    "backend": "cuda" if index else args.backend, "delivery": "plain",
                    "seed": None if index else seed, "reference": str(reference),
                    "reference_sha256": reference_hash,
                    "reference_text": reference_text,
                    "reference_text_source": "local Whisper base, unreviewed",
                    "chapter": 1745 if cue is not None else 2882, "cue": cue,
                    "spoken": spoken, "render_seconds": round(wall, 3),
                    "duration_seconds": round(duration, 3),
                    "render_seconds_per_finished_minute": round(wall * 60 / duration, 2),
                    "reused_from": str(args.reuse_scene) if reused is not None else None,
                })
                print(actor, label, "reused" if reused is not None else "recorded", flush=True)
    finally:
        if index is not None:
            index.__exit__(None, None, None)
    cold_wall = time.monotonic() - run_start
    manifest(out / (args.engine + "-runtime.json"), {
        "cold_wall_seconds": round(cold_wall, 2),
        "finished_audio_seconds": round(finished_seconds, 2),
        "reused_audio_seconds": round(reused_seconds, 2),
        "cold_seconds_per_finished_minute": (round(cold_wall * 60 / finished_seconds, 2)
                                             if finished_seconds else None),
        "index_load_seconds": None if model_load is None else round(model_load, 2),
        **gpu.report(),
        "memory_scope": "GPU 0 sampled every 0.5 s, includes desktop usage",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=ENGINE_NAMES)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--sunny-alt", type=Path, required=True)
    parser.add_argument("--nephis-alt", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--backend", choices=["vulkan", "cuda", "cpu"], default="vulkan")
    parser.add_argument("--reuse-scene", type=Path,
                        help="Reuse exactly matching audio.cpp recordings from an audition scene directory")
    args = parser.parse_args()
    if args.reuse_scene is not None:
        if args.engine == "index":
            parser.error("--reuse-scene requires an audio.cpp engine")
        args.reuse_scene = args.reuse_scene.resolve(strict=True)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")
    out = args.out or Path(tempfile.mkdtemp(prefix="reference-audition-", dir=BENCH))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(out, flush=True)
    sheet = json.loads(args.sheet.read_text(encoding="utf-8"))
    cues = {cue["index"]: cue for cue in sheet["cues"]}
    alts = {"Sunny": args.sunny_alt, "Nephis": args.nephis_alt}
    specs = {}
    for actor, cue_id in CAST.items():
        if cue_id is None:
            current = (VOICES / "cassie.wav").resolve(strict=True)
            spoken = CASSIE_TEXT
        else:
            cue = cues[cue_id]
            if cue["actor"] != actor:
                parser.error(f"Unexpected speaker for cue {cue_id}")
            current = Path(cue["reference"]).resolve(strict=True)
            spoken = cue["spoken"]
        alternate = alts.get(actor, current).resolve(strict=True)
        if cue_id is not None and file_digest(current) == file_digest(alternate):
            parser.error(f"{actor} needs two distinct references")
        specs[actor] = [("current", cue_id, current, spoken)]
        if cue_id is not None:
            specs[actor].append(("candidate", cue_id, alternate, spoken))
    print("Preparing reference transcripts", flush=True)
    paths = dict.fromkeys(path for variants in specs.values() for _, _, path, _ in variants)
    transcript_dir = out / "reference-transcripts"
    transcript_dir.mkdir(exist_ok=True)
    args.transcripts = {}
    asr = None
    for path in paths:
        cached = transcript_dir / (file_digest(path) + ".txt")
        if not cached.is_file():
            if asr is None:
                from faster_whisper import WhisperModel

                asr = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4,
                                   local_files_only=True)
            transcript = transcribe(asr, path)
            if transcript:
                cached.write_text(transcript, encoding="utf-8")
        args.transcripts[path] = cached.read_text(encoding="utf-8") if cached.is_file() else ""
        print("Reference prepared:", path.name, flush=True)
    if not all(args.transcripts.values()):
        parser.error("Each reference must contain intelligible speech")
    del asr
    print(f"Starting {args.engine} recordings", flush=True)
    with GpuMemory() as gpu:
        render(args, out, specs, gpu)
    reviewer = TakeReviewer()
    for actor, variants in specs.items():
        pair = out / (args.engine + "-" + actor.lower())
        for label, _, _, spoken in variants:
            record = pair / (label + ".json")
            detail = json.loads(record.read_text(encoding="utf-8"))
            detail["audit"] = reviewer.check((pair / (label + ".wav")).read_bytes(), spoken)
            if detail["audit"]["status"] != "checked":
                raise RuntimeError("The local read-back model could not verify the recordings")
            manifest(record, detail)
    publish_comparisons(out)


if __name__ == "__main__":
    main()
