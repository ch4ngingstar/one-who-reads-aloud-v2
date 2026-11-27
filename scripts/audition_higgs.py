"""Compare dialogue against a timed master using identical narrator audio and gaps."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from speech_audio import check_utterance, studio_pcm
from take_review import TakeReviewer
from gpu_measurement import GpuMemory


def excerpt(master, start, duration):
    return subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(master),
        "-t", str(duration), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "s16le", "-"])


def match_level(pcm, original):
    import numpy as np
    source = np.frombuffer(pcm, dtype="<i2").astype(float)
    target = np.frombuffer(original, dtype="<i2").astype(float)
    gain = min(np.sqrt(np.mean(target**2) / max(1, np.mean(source**2))),
               29000 / max(1, np.max(np.abs(source))))
    return np.rint(source * gain).astype("<i2").tobytes()


def timed_audio(master, cue):
    return excerpt(master, cue["start_ms"] / 1000, (cue["end_ms"] - cue["start_ms"]) / 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("first", type=int)
    parser.add_argument("last", type=int)
    parser.add_argument("--backend", default="vulkan", choices=["vulkan","cpu","cuda"])
    parser.add_argument("--family", default="higgs_audio_tts", choices=["higgs_audio_tts", "fish_audio"])
    parser.add_argument("--reference-seconds", type=float, help="Compare a shorter cut of the same actor recording")
    parser.add_argument("--existing-master", type=Path, help="Use already recorded dialogue from a matched timed master")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--higgs-emotion", choices=["confusion", "amusement", "surprise"],
                        help="Apply one control token in a single-line Higgs direction comparison")
    args = parser.parse_args()
    sheet = json.loads(args.master.with_suffix(".performance.json").read_text("utf-8"))
    cues = [c for c in sheet["cues"] if args.first <= c["index"] <= args.last]
    if not cues or not any(c["actor"] != "Narrator" for c in cues): parser.error("Choose a scene with dialogue")
    if args.higgs_emotion and (args.family != "higgs_audio_tts" or len(cues) != 1 or args.existing_master):
        parser.error("Use a single Higgs dialogue cue for a direction comparison")
    if args.existing_master and args.reference_seconds:
        parser.error("A saved take already has a fixed reference")
    cli = ROOT/"models/audio-runtime/audiocpp_cli.exe"
    filename = ("higgs-audio-v3-tts-4b-q8_0.gguf" if args.family == "higgs_audio_tts"
                else "fish-audio-s2-pro-q8_0.gguf")
    previous = {}
    if args.existing_master:
        saved = json.loads(args.existing_master.with_suffix(".performance.json").read_text("utf-8"))
        previous = {c["index"]: c for c in saved["cues"]}
    else:
        model = next((ROOT/"models/audio-cpp").rglob(filename), None)
        if model is None or not cli.is_file():
            parser.error(f"Missing verified runtime or {filename}")
    prefix = "saved" if previous else args.family
    out = Path(tempfile.mkdtemp(prefix=prefix+"-scene-",dir=args.master.parent))
    print(out, flush=True)
    if not args.existing_master:
        from faster_whisper import WhisperModel
        asr = WhisperModel("base",device="cpu",compute_type="int8",cpu_threads=4,local_files_only=True)
        reviewer = TakeReviewer()
        reviewer.model = asr
    refs, takes, control, report = {}, [], [], []
    for n,c in enumerate(cues):
        original = timed_audio(args.master, c)
        if n:
            gap = bytes(48 * max(0,c["start_ms"]-cues[n-1]["end_ms"]))
            takes.append(gap)
            control.append(gap)
        control.append(original)
        if c["actor"] == "Narrator":
            takes.append(original)
            continue
        if args.existing_master:
            other = previous[c["index"]]
            if any(other[k] != c[k] for k in ("actor", "spoken", "kind", "reference_hash")):
                raise ValueError(f"Saved take differs in identity or script at cue {c['index']}")
            takes.append(match_level(timed_audio(args.existing_master, other), original))
            report.append({"index": c["index"], "speaker": c["actor"], "spoken": c["spoken"],
                           "family": other["renderer"], "source_master": str(args.existing_master.resolve()),
                           "reference": other["reference"], "reference_hash": other["reference_hash"],
                           "audit": other.get("audit")})
            continue
        ref=c["reference"]
        if hashlib.sha256(Path(ref).read_bytes()).hexdigest() != c["reference_hash"]:
            raise ValueError(f"Registered reference changed since recording cue {c['index']}")
        if args.reference_seconds is not None:
            if not 3 <= args.reference_seconds <= 10:
                parser.error("Reference cuts must be between three and ten seconds")
            clipped = out / (c["reference_hash"] + ".wav")
            if not clipped.exists():
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", ref,
                                "-t", str(args.reference_seconds), "-c:a", "pcm_s16le", str(clipped)], check=True)
            ref = str(clipped)
        if ref not in refs:
            segments,_=asr.transcribe(ref,language="en",condition_on_previous_text=False)
            refs[ref]=" ".join(s.text.strip() for s in segments)
        path=out/f"line_{c['index']}.wav"
        ts=time.monotonic()
        prompt = (f"<|emotion:{args.higgs_emotion}|>" if args.higgs_emotion else "") + c["spoken"]
        cmd=[str(cli),"--task","clon","--family",args.family,"--model",str(model),
             "--backend",args.backend,"--text",prompt,"--voice-ref",ref,"--reference-text",refs[ref],
             "--seed",str(args.seed),"--max-tokens","512","--out",str(path)]
        with (out/f"line_{c['index']}.log").open("wb") as log, GpuMemory() as gpu:
            subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        elapsed = time.monotonic() - ts
        raw=studio_pcm(path.read_bytes())
        check_utterance(raw,c["spoken"])
        with wave.open(io.BytesIO(raw),"rb") as f:
            duration = f.getnframes() / f.getframerate()
            takes.append(match_level(f.readframes(f.getnframes()), original))
        report.append({"index":c["index"],"speaker":c["actor"],"wall_s":round(elapsed,2),
                       "audio_s": duration, "render_real_time_factor": round(elapsed / duration, 3),
                       **gpu.report(), "seed": args.seed, "higgs_emotion": args.higgs_emotion,
                       "reference_hash": hashlib.sha256(Path(ref).read_bytes()).hexdigest(),
                       "reference_text":refs[ref],"reference":ref,"spoken":c["spoken"],
                       "family":args.family,"model":str(model),"backend":args.backend,
                       "audit":reviewer.check(raw,c["spoken"])})
        (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        print("Recorded", c["actor"], "line", c["index"], flush=True)
    for name,pcm in [("current",control),("candidate",takes)]:
        with wave.open(str(out/(name+".wav")),"wb") as f:
            f.setparams((1,2,24000,0,"NONE",""));f.writeframes(b"".join(pcm))
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
