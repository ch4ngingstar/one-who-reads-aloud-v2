"""
Emotion-vector effect evaluation — the core question: do the per-line emotion
vectors actually change the voice, and by how much?

For a fixed reference voice and a small set of probe sentences, synthesize each
sentence under every tag in INDEXTTS2_EMOTION_VECTORS plus a forced-neutral
baseline (emo_vector=None → pure timbre). Extract prosody features (F0 mean/std,
RMS energy, duration, speaking rate) per clip with librosa, then build an
emotion×feature delta matrix vs neutral. Tags whose deltas are below threshold on
EVERY feature are flagged **inert** — they sound the same as neutral, i.e. the
emotion is wasted. Those are exactly the entries to retune in Phase 2.

This is the ONLY eval script that loads the TTS model (GPU). It does so inside a
single `with TTSEngine(...)` block to respect the 12 GB VRAM lifecycle. Keep the
probe set small. Read-only w.r.t. pipeline state (writes only to its own out dir).

Run from repo root (after the model + a reference voice exist):
    python scripts/eval_emotion.py --ref src/data/voices/nephis.wav
"""

import argparse
import sys
from pathlib import Path

from eval_common import (
    DEFAULT_MODEL_DIR, DEFAULT_DB, REPORTS_DIR, write_csv, write_json,
)

# Emotion-neutral content so the vector — not the words — drives the prosody.
PROBE_SENTENCES = [
    "The door stood at the end of the corridor.",
    "He walked across the room and looked outside.",
    "They had been travelling since the early morning.",
    "She placed the object carefully on the table.",
    "The city stretched out beneath the grey sky.",
    "Nothing moved among the trees for a long while.",
    "He counted the steps as he climbed the stair.",
    "The water was cold and the wind was rising.",
    "A single light burned in the distant window.",
    "They spoke about the road that lay ahead.",
]

FEATURES = ["f0_mean", "f0_std", "rms_mean", "duration", "rate"]

# An emotion is "inert" only if it fails to move ANY of these beyond its band.
# Relative bands (fraction of the neutral value) for scale-dependent features,
# absolute Hz band for f0_std which can be ~0 at neutral.
INERT_REL = {"f0_mean": 0.04, "rms_mean": 0.08, "rate": 0.04}
INERT_ABS = {"f0_std": 5.0}  # Hz


def extract_features(wav_path: str, char_count: int) -> dict:
    """Prosody features for one clip. Imported deps are lazy so tests can patch.
    rate = characters-per-second (a proxy for speaking pace)."""
    import librosa
    import numpy as np

    y, sr = librosa.load(wav_path, sr=None, mono=True)
    duration = float(len(y) / sr) if sr else 0.0
    f0, _, _ = librosa.pyin(y, fmin=70, fmax=400, sr=sr)
    f0_voiced = f0[~np.isnan(f0)] if f0 is not None else np.array([])
    rms = librosa.feature.rms(y=y)[0]
    return {
        "f0_mean": float(np.mean(f0_voiced)) if f0_voiced.size else 0.0,
        "f0_std": float(np.std(f0_voiced)) if f0_voiced.size else 0.0,
        "rms_mean": float(np.mean(rms)) if rms.size else 0.0,
        "duration": duration,
        "rate": (char_count / duration) if duration > 0 else 0.0,
    }


def aggregate(feature_dicts: list) -> dict:
    """Mean of each feature across a tag's probe clips."""
    if not feature_dicts:
        return {k: 0.0 for k in FEATURES}
    return {k: sum(d[k] for d in feature_dicts) / len(feature_dicts) for k in FEATURES}


def deltas_vs_neutral(tag_means: dict, neutral: dict) -> dict:
    """Per-tag, per-feature signed delta + relative delta vs the neutral baseline."""
    out = {}
    for tag, means in tag_means.items():
        row = {}
        for f in FEATURES:
            d = means[f] - neutral[f]
            base = abs(neutral[f]) if neutral[f] else 0.0
            row[f] = d
            row[f + "_rel"] = (d / base) if base else (0.0 if d == 0 else float("inf"))
        out[tag] = row
    return out


def flag_inert(delta_matrix: dict) -> list:
    """A tag is inert if it moves NO feature beyond its band vs neutral."""
    inert = []
    for tag, row in delta_matrix.items():
        moved = False
        for f, band in INERT_REL.items():
            if abs(row.get(f + "_rel", 0.0)) >= band:
                moved = True
        for f, band in INERT_ABS.items():
            if abs(row.get(f, 0.0)) >= band:
                moved = True
        if not moved:
            inert.append(tag)
    return inert


def synthesize_matrix(engine, ref_audio: str, sentences: list, out_dir: Path,
                      tags: "list[str] | None" = None) -> dict:
    """Synthesize every (tag, sentence) pair. Returns {tag: [(wav_path, char_count)]}.
    The neutral baseline uses emo_vector=None to match _resolve_emotion('neutral').

    `tags` restricts which emotions are synthesized (neutral is always included so
    deltas can be computed) — used for fast targeted re-runs after a retune.
    """
    from tts_engine import INDEXTTS2_EMOTION_VECTORS

    if tags is not None:
        wanted = {"neutral", *tags}
        items = [(t, v) for t, v in INDEXTTS2_EMOTION_VECTORS.items() if t in wanted]
    else:
        items = list(INDEXTTS2_EMOTION_VECTORS.items())

    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for tag, (vec, alpha) in items:
        tag_dir = out_dir / tag
        tag_dir.mkdir(exist_ok=True)
        clips = []
        for i, sent in enumerate(sentences):
            emo_vec = None if tag == "neutral" else vec
            emo_alpha = 0.0 if tag == "neutral" else alpha
            wav_bytes = engine._synthesize(sent, ref_audio, emo_vec, emo_alpha)
            wp = tag_dir / f"probe_{i:02d}.wav"
            wp.write_bytes(wav_bytes)
            clips.append((str(wp), len(sent)))
            print(f"  [{tag:<10}] probe {i+1}/{len(sentences)}", flush=True)
        result[tag] = clips
    return result


def build_report(synth_result: dict) -> dict:
    """Extract features for every clip, aggregate per tag, compute deltas, flag inert."""
    tag_means = {}
    for tag, clips in synth_result.items():
        feats = [extract_features(p, n) for (p, n) in clips]
        tag_means[tag] = aggregate(feats)
    neutral = tag_means["neutral"]
    non_neutral = {t: m for t, m in tag_means.items() if t != "neutral"}
    delta_matrix = deltas_vs_neutral(non_neutral, neutral)
    return {
        "tag_means": tag_means,
        "delta_matrix": delta_matrix,
        "inert_tags": flag_inert(delta_matrix),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure emotion-vector effect on prosody.")
    ap.add_argument("--ref", required=True, help="reference voice WAV (timbre clip)")
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--n-probes", type=int, default=len(PROBE_SENTENCES))
    ap.add_argument("--tags", default=None,
                    help="comma-separated subset of emotion tags (neutral auto-included)")
    ap.add_argument("--label", default=None,
                    help="suffix for output files (e.g. 'retune') to avoid clobbering baseline")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    suffix = f"_{args.label}" if args.label else ""
    out_dir = Path(args.out_dir) if args.out_dir else REPORTS_DIR / f"eval_emotion_clips{suffix}"
    tag_filter = [t.strip() for t in args.tags.split(",")] if args.tags else None

    ref = Path(args.ref)
    if not ref.exists():
        print(f"[eval] reference voice not found: {ref}", file=sys.stderr)
        sys.exit(2)

    from state_manager import StateManager
    from tts_engine import TTSEngine

    sm = StateManager(args.db)
    sentences = PROBE_SENTENCES[: args.n_probes]
    n_tags = len(tag_filter) if tag_filter else 13
    print(f"[eval] synthesizing {len(sentences)} probes × {n_tags} tag(s) (GPU)...")
    with TTSEngine(sm, out_dir, model_dir=args.model_dir) as engine:
        synth = synthesize_matrix(engine, str(ref), sentences, out_dir, tags=tag_filter)

    print("[eval] extracting prosody features + computing deltas...")
    report = build_report(synth)

    rows = []
    for tag, row in report["delta_matrix"].items():
        rows.append({
            "emotion": tag,
            **{f: round(row[f], 3) for f in FEATURES},
            **{f + "_rel": round(row[f + "_rel"], 3) for f in INERT_REL},
            "inert": "yes" if tag in report["inert_tags"] else "",
        })
    csv_path = REPORTS_DIR / f"eval_emotion{suffix}.csv"
    write_csv(csv_path, rows,
              ["emotion", *FEATURES, *(f + "_rel" for f in INERT_REL), "inert"])
    write_json(REPORTS_DIR / f"eval_emotion{suffix}.json", report)

    print(f"[eval] wrote {csv_path}")
    if report["inert_tags"]:
        print(f"[eval] INERT (no measurable effect vs neutral): "
              f"{', '.join(report['inert_tags'])}")
    else:
        print("[eval] all emotion tags produce a measurable prosody change.")


if __name__ == "__main__":
    main()
