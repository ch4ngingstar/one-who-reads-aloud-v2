"""
Voice-consistency evaluation — does each character keep their voice, and does a
strong emotion vector degrade speaker identity (emotion/identity decoupling)?

For each diarized line with audio, resolve the speaker's reference timbre clip
(the same resolution TTS used), embed both the reference and the generated line
with resemblyzer, and take cosine similarity. Low similarity = voice drift or
identity bleed. Each line also carries its emotion's emo_alpha so you can see
whether high-alpha lines lose similarity.

Read-only. Run from repo root:
    pip install -r requirements-eval.txt
    python scripts/eval_speaker.py --chapter 264 --by-index
"""

import argparse
import sys
from pathlib import Path

from eval_common import (
    DEFAULT_DB, REPORTS_DIR, pick_project, resolve_chapter_ids,
    line_wavs_for_chapter, write_csv,
)


def load_encoder():
    """Return an embed(path:str) -> vector callable backed by resemblyzer.
    Lazy import so unit tests inject a fake embedder instead."""
    from resemblyzer import VoiceEncoder, preprocess_wav

    encoder = VoiceEncoder()

    def embed(path: str):
        wav = preprocess_wav(Path(path))
        return encoder.embed_utterance(wav)

    return embed


def cosine(a, b) -> float:
    import numpy as np

    a, b = np.asarray(a), np.asarray(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _emo_alpha(emotion: str) -> float:
    from tts_engine import INDEXTTS2_EMOTION_VECTORS

    return INDEXTTS2_EMOTION_VECTORS.get(emotion, ([], 0.0))[1]


def score_chapter(sm, chapter_id: int, voice_map: dict, embed, sim_threshold=0.75) -> dict:
    """Cosine-similarity every audio-backed line against its resolved reference
    timbre. Returns {rows, per_speaker, n_scored, mean_sim, n_flagged}."""
    from tts_engine import TTSEngine

    ref_cache = {}

    def ref_embed(ref_path: str):
        if ref_path not in ref_cache:
            ref_cache[ref_path] = embed(ref_path)
        return ref_cache[ref_path]

    rows = []
    per_speaker = {}  # speaker -> [sim, ...]
    for line, wav in line_wavs_for_chapter(sm, chapter_id):
        if wav is None:
            continue
        ref_path = TTSEngine._resolve_ref_audio(line["speaker"], line["emotion"], voice_map)
        if not ref_path:
            continue
        from state_manager import _resolve_stored_path
        ref_resolved = _resolve_stored_path(ref_path)
        if not Path(ref_resolved).exists():
            continue
        sim = cosine(ref_embed(str(ref_resolved)), embed(str(wav)))
        per_speaker.setdefault(line["speaker"], []).append(sim)
        rows.append({
            "chapter_id": chapter_id, "line_index": line["line_index"],
            "speaker": line["speaker"], "emotion": line["emotion"],
            "emo_alpha": _emo_alpha(line["emotion"]),
            "similarity": round(sim, 4),
            "flagged": "yes" if sim < sim_threshold else "",
        })
    sims = [r["similarity"] for r in rows]
    speaker_means = {sp: round(sum(v) / len(v), 4) for sp, v in per_speaker.items()}
    return {
        "rows": rows,
        "per_speaker": speaker_means,
        "n_scored": len(sims),
        "mean_sim": round(sum(sims) / len(sims), 4) if sims else None,
        "n_flagged": sum(1 for r in rows if r["flagged"] == "yes"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Speaker/voice consistency via embeddings.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--project", default=None)
    ap.add_argument("--chapter", type=int, nargs="*", default=None)
    ap.add_argument("--by-index", action="store_true")
    ap.add_argument("--sim-threshold", type=float, default=0.75)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from state_manager import StateManager
    sm = StateManager(args.db)
    project_id = pick_project(sm, args.project)
    chapter_ids = resolve_chapter_ids(sm, project_id, args.chapter, args.by_index)
    if not chapter_ids:
        print("[eval] No chapters with diarized lines.", file=sys.stderr)
        sys.exit(2)

    voice_map = sm.get_voice_map()
    print("[eval] loading resemblyzer voice encoder...")
    embed = load_encoder()

    all_rows = []
    for cid in chapter_ids:
        res = score_chapter(sm, cid, voice_map, embed, args.sim_threshold)
        all_rows.extend(res["rows"])
        print(f"  ch_id={cid}: scored={res['n_scored']} meanSim={res['mean_sim']} "
              f"flagged={res['n_flagged']}")
        for sp, m in sorted(res["per_speaker"].items(), key=lambda kv: kv[1]):
            print(f"      {sp:<24} mean_sim={m}")

    out = args.out or str(REPORTS_DIR / "eval_speaker.csv")
    write_csv(Path(out), all_rows,
              ["chapter_id", "line_index", "speaker", "emotion", "emo_alpha",
               "similarity", "flagged"])
    print(f"[eval] wrote {out} ({len(all_rows)} lines)")


if __name__ == "__main__":
    main()
