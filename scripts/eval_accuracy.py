"""
TTS accuracy evaluation — does the synthesized audio actually say the text?

For every diarized line of a chapter, run ASR (faster-whisper) on the generated
WAV and compare the transcript to the line's intended text (the byte-exact
segmenter output stored in the DB) using WER/CER (jiwer). High-WER lines surface
dropped words, hallucinated audio, and truncation.

Read-only. Run from repo root:
    pip install -r requirements-eval.txt
    python scripts/eval_accuracy.py --chapter 264 --by-index
    python scripts/eval_accuracy.py            # every chapter with audio

Output: docs/eval_accuracy_<project>.csv (+ stdout summary). Exit 0 unless a
fatal error; the WER threshold only flags rows, it does not fail the run.
"""

import argparse
import re
import sys

from eval_common import (
    DEFAULT_DB, DEFAULT_AUDIO_ROOT, REPORTS_DIR,
    pick_project, resolve_chapter_ids, line_wavs_for_chapter, write_csv,
)

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — so WER measures words
    spoken, not casing/punctuation the ASR cannot recover."""
    return _WS.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def load_whisper(model_size: str = "base", device: str = "cpu",
                 compute_type: str = "int8"):
    """Return a transcribe(path:str) -> str callable backed by faster-whisper.
    Imported lazily so unit tests can inject a fake transcriber instead."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(path: str) -> str:
        segments, _ = model.transcribe(path, language="en", beam_size=1)
        return " ".join(seg.text for seg in segments)

    return transcribe


def _wer_cer(ref: str, hyp: str):
    """WER and CER via jiwer on already-normalized strings. Empty reference is
    treated as 1.0 error if anything was spoken, else 0.0."""
    import jiwer

    if not ref:
        return (1.0 if hyp else 0.0), (1.0 if hyp else 0.0)
    return jiwer.wer(ref, hyp), jiwer.cer(ref, hyp)


def score_chapter(sm, chapter_id: int, transcribe, wer_threshold: float = 0.4) -> dict:
    """ASR-score every audio-backed line of a chapter. Returns
    {rows, n_scored, n_missing, mean_wer, mean_cer, n_flagged}."""
    rows, wers, cers = [], [], []
    n_missing = 0
    for line, wav in line_wavs_for_chapter(sm, chapter_id):
        ref = normalize(line["text"])
        if wav is None:
            n_missing += 1
            rows.append({
                "chapter_id": chapter_id, "line_index": line["line_index"],
                "speaker": line["speaker"], "wer": "", "cer": "",
                "flagged": "", "ref": line["text"][:120], "hyp": "(no audio)",
            })
            continue
        hyp = normalize(transcribe(str(wav)))
        wer, cer = _wer_cer(ref, hyp)
        wers.append(wer)
        cers.append(cer)
        rows.append({
            "chapter_id": chapter_id, "line_index": line["line_index"],
            "speaker": line["speaker"], "wer": round(wer, 4), "cer": round(cer, 4),
            "flagged": "yes" if wer >= wer_threshold else "",
            "ref": line["text"][:120], "hyp": hyp[:120],
        })
    n_flagged = sum(1 for r in rows if r["flagged"] == "yes")
    return {
        "rows": rows,
        "n_scored": len(wers),
        "n_missing": n_missing,
        "mean_wer": round(sum(wers) / len(wers), 4) if wers else None,
        "mean_cer": round(sum(cers) / len(cers), 4) if cers else None,
        "n_flagged": n_flagged,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="TTS accuracy (WER/CER) via ASR.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--project", default=None)
    ap.add_argument("--chapter", type=int, nargs="*", default=None,
                    help="chapter ids (or chapter_index with --by-index)")
    ap.add_argument("--by-index", action="store_true")
    ap.add_argument("--model", default="base", help="faster-whisper model size")
    ap.add_argument("--wer-threshold", type=float, default=0.4)
    ap.add_argument("--out", default=None, help="CSV output path")
    args = ap.parse_args()

    from state_manager import StateManager
    sm = StateManager(args.db)
    project_id = pick_project(sm, args.project)
    chapter_ids = resolve_chapter_ids(sm, project_id, args.chapter, args.by_index)
    if not chapter_ids:
        print("[eval] No chapters with diarized lines.", file=sys.stderr)
        sys.exit(2)

    print(f"[eval] loading faster-whisper '{args.model}' (cpu/int8)...")
    transcribe = load_whisper(args.model)

    all_rows, summaries = [], []
    for cid in chapter_ids:
        res = score_chapter(sm, cid, transcribe, args.wer_threshold)
        all_rows.extend(res["rows"])
        summaries.append((cid, res))
        print(f"  ch_id={cid}: scored={res['n_scored']} missing={res['n_missing']} "
              f"meanWER={res['mean_wer']} flagged={res['n_flagged']}")

    out = args.out or str(REPORTS_DIR / "eval_accuracy.csv")
    write_csv(__import__("pathlib").Path(out), all_rows,
              ["chapter_id", "line_index", "speaker", "wer", "cer",
               "flagged", "ref", "hyp"])
    print(f"[eval] wrote {out} ({len(all_rows)} lines)")


if __name__ == "__main__":
    main()
