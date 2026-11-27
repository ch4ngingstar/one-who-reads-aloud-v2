"""Check paired chapter editions and prepare the frozen cast listening comparisons."""

import argparse
from bisect import bisect_left, bisect_right
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

if __package__:
    from .build_listening_pack import read_json
else:
    from build_listening_pack import read_json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from casting import SPEAKER_ALIASES


def words(text):
    return re.findall(r"\w+", text)


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def actor(name):
    name = name.strip().title()
    return SPEAKER_ALIASES.get(name, name).casefold()


def source_anchors(db, chapter):
    chapter_id = chapter["chapter_id"]
    chunks = dict(db.execute("SELECT chunk_index,text FROM chunks WHERE chapter_id=? ORDER BY chunk_index",
                             (chapter_id,)))
    text = "\n\n".join(chunks.values())
    if not chunks or digest(text) != chapter["source_sha256"]:
        raise ValueError(f"chapter {chapter_id}: original chapter hash changed")
    if chapter["chunk_sources"] != [
        {"chunk_index": i, "sha256": digest(chunk)} for i, chunk in chunks.items()
    ]:
        raise ValueError(f"chapter {chapter_id}: original chunk boundaries or hashes changed")
    chunk_offsets = {}
    offset = 0
    for i, chunk in chunks.items():
        chunk_offsets[i] = offset
        offset += len(words(chunk))
    anchors = {}
    for excerpt in chapter["excerpts"]:
        spans = []
        for cue in excerpt["cues"]:
            i = cue["chunk_index"]
            start, end = cue["chunk_char_start"], cue["chunk_char_end"]
            original = chunks[i][start:end]
            if original != cue["source_text"] or digest(original) != cue["source_text_sha256"]:
                raise ValueError(f"{excerpt['id']}: frozen source span or hash no longer matches")
            anchor_chunk = chunks[cue["attribution_anchor_chunk"]]
            anchor_start = cue["attribution_anchor_char_start"]
            anchor = cue["attribution_anchor"]
            if anchor_chunk[anchor_start:anchor_start + len(anchor)] != anchor:
                raise ValueError(f"{excerpt['id']}: frozen attribution anchor no longer matches")
            first_word = chunk_offsets[i] + len(words(chunks[i][:start]))
            spans.append((first_word, first_word + len(words(original)), cue["expected_role"]))
        anchors[excerpt["id"]] = spans
    return words(text), anchors


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def check_edition(master, sheet, source_words, anchors):
    duration = probe_duration(master)
    cues = sheet["cues"]
    if not cues:
        raise ValueError("timed script contains no cues")
    declared = sheet["duration_ms"]
    if not number(declared) or abs(duration * 1000 - declared) > 500:
        raise ValueError(f"timed script declares {declared} ms, decoded master is {duration:.3f} s")
    if "master_bytes" in sheet and sheet["master_bytes"] != master.stat().st_size:
        raise ValueError("timed script master_bytes does not match the supplied master")
    indices, offsets, flattened, narrators = [], [0], [], set()
    narrator_spans = []
    previous_end = 0
    for cue in cues:
        index, start, end = cue["index"], cue["start_ms"], cue["end_ms"]
        if type(index) is not int or index < 0 or (indices and index <= indices[-1]):
            raise ValueError(f"cue {index}: indices must be positive-order and unique")
        if not (number(start) and number(end) and previous_end <= start < end <= min(declared, duration * 1000 + 5)):
            raise ValueError(f"cue {index}: invalid timestamp range {start}–{end} ms after {previous_end} ms")
        previous_end = end
        indices.append(index)
        flattened.extend(words(cue["source"]))
        offsets.append(len(flattened))
        if actor(cue["actor"]) == "narrator":
            reference = cue.get("reference_hash")
            renderer = cue.get("renderer", sheet.get("renderer"))
            if (not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{64}", reference)
                    or not isinstance(renderer, str) or not renderer.strip()
                    or cue.get("fallback") is not False or actor(cue["speaker"]) != "narrator"):
                raise ValueError(f"cue {index}: missing approved narrator reference/renderer or fallback used")
            narrators.add((reference, renderer))
            if offsets[-2] != offsets[-1]:
                if narrator_spans and narrator_spans[-1][1] == offsets[-2]:
                    narrator_spans[-1][1] = offsets[-1]
                else:
                    narrator_spans.append([offsets[-2], offsets[-1]])
    if flattened != source_words:
        difference = next((i for i, (a, b) in enumerate(zip(flattened, source_words)) if a != b),
                          min(len(flattened), len(source_words)))
        raise ValueError(f"source word {difference + 1}: expected {source_words[difference:difference + 5]!r}, "
                         f"found {flattened[difference:difference + 5]!r} "
                         f"({len(flattened)} words in script, {len(source_words)} in source)")
    if len(narrators) != 1:
        raise ValueError(f"expected one retained narrator reference and renderer, found {len(narrators)}")

    matches, errors = {}, []
    for excerpt_id, spans in anchors.items():
        ranges = []
        for first_word, after_last, role in spans:
            # Complete source alignment locates repeated text by occurrence, even when
            # intervening cues were resegmented or assigned new indices.
            first = bisect_right(offsets, first_word) - 1
            past = bisect_left(offsets, after_last)
            if first >= past or offsets[first] != first_word or offsets[past] != after_last:
                errors.append(f"{excerpt_id}: source span {first_word + 1}–{after_last} is merged "
                              "with surrounding words and has no exact cue time boundaries")
                continue
            roles = [(cue["index"], cue["speaker"], cue["actor"]) for cue in cues[first:past]
                     if cue["kind"] != "dialogue" or actor(cue["actor"]) != actor(role)
                     or actor(cue["speaker"]) != actor(role) or cue.get("fallback") is not False]
            if roles:
                errors.append(f"{excerpt_id}: expected {role} in dialogue, found {roles!r} "
                              "(cue index, speaker, voice actor), or a fallback was used")
            ranges.append((first, past))
        if len(ranges) != len(spans):
            continue
        start, stop = ranges[0][0], ranges[-1][1]
        lower = cues[start - 1]["end_ms"] if start else 0
        upper = cues[stop]["start_ms"] if stop < len(cues) else min(declared, duration * 1000)
        start_ms = max(lower, cues[start]["start_ms"] - 160)
        end_ms = min(upper, cues[stop - 1]["end_ms"] + 160)
        matches[excerpt_id] = {"start_ms": start_ms, "end_ms": end_ms,
                               "cue_indices": indices[start:stop],
                               "spoken_words": words(" ".join(cue["spoken"] for cue in cues[start:stop]))}
        if not matches[excerpt_id]["spoken_words"]:
            errors.append(f"{excerpt_id}: timed script has no spoken copy in the selected interval")
    return {"duration_seconds": duration, "narrator": next(iter(narrators)),
            "narrator_spans": narrator_spans, "matches": matches, "errors": errors}


def probe_duration(master):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type,duration:format=duration", "-of", "json", str(master)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams")
    if not streams:
        raise ValueError("master has no audio stream")
    seconds = float(streams[0].get("duration") or data["format"]["duration"])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("master has no measurable audio stream")
    return seconds


def check_benchmark(path, master, chapter, duration, sheet):
    report = read_json(path)
    errors = []
    audio = Path(report["audio"])
    candidates = (audio,) if audio.is_absolute() else (audio, path.parent / audio, ROOT / audio)
    if not any(p.is_file() and p.samefile(master) for p in candidates):
        errors.append(f"report audio {audio} does not identify the supplied candidate master")
    if report.get("chapter") != chapter["title"] or report.get("lines") != len(sheet["cues"]):
        errors.append("report chapter or line count does not match the supplied candidate")
    measured = report.get("audio_seconds")
    if not number(measured) or abs(measured - duration) > 0.05:
        errors.append(f"report audio duration {measured!r} does not match decoded duration {duration:.3f} s")
    wall = report.get("wall_seconds")
    if not number(wall) or not 0 < wall <= 2400 or report.get("within_forty_minutes") is not True:
        errors.append(f"candidate cold wall time {wall!r} s did not meet the 2,400 s limit")
    if report.get("reused_labels") is not False:
        errors.append("benchmark must explicitly report reused_labels=false")
    if (type(report.get("cache_hits")) is not int or report["cache_hits"] != 0
            or any(cue.get("cached") is not False for cue in sheet["cues"])):
        errors.append("benchmark and all candidate cues must explicitly show zero cached takes")
    return wall, errors


def clip_args(master, match):
    seconds = (match["end_ms"] - match["start_ms"]) / 1000
    return ["ffmpeg", "-nostdin", "-ss", str(match["start_ms"] / 1000), "-t", str(seconds),
            "-i", str(master), "-map", "0:a:0", "-ac", "1"]


def clip_level(master, match):
    result = subprocess.run(
        [*clip_args(master, match), "-af", "aformat=channel_layouts=mono,loudnorm=print_format=json",
         "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    )
    levels = json.loads(result.stderr[result.stderr.rindex("{"):])
    loudness, peak = float(levels["input_i"]), float(levels["input_tp"])
    if not all(map(math.isfinite, (loudness, peak))):
        raise ValueError("selected clip has no measurable speech level")
    return loudness, peak


def generate_comparisons(jobs, output):
    comparisons = []
    for key, roles, editions in jobs:
        levels = [clip_level(master, match) for _, master, match in editions]
        # Use equal, constant gain targets for both sides and preserve within-clip dynamics.
        target = min(-20, *(loudness - peak - 2 for loudness, peak in levels))
        variants = []
        for (label, master, match), (loudness, _) in zip(editions, levels, strict=True):
            path = Path("clips") / f"{key}-{label}.wav"
            (output / path).parent.mkdir(exist_ok=True)
            subprocess.run(
                [*clip_args(master, match), "-v", "error", "-y", "-af",
                 f"volume={target - loudness:.3f}dB", "-ar", "24000", "-c:a", "pcm_s16le",
                 str(output / path)], check=True, capture_output=True, text=True,
            )
            variants.append({"label": label, "path": path.as_posix(),
                             "chapter_master": str(master.resolve()), "cue_indices": match["cue_indices"]})
        comparisons.append({"id": key, "kind": "scene" if len(roles) > 1 else "line",
                            "roles": list(dict.fromkeys(roles)), "variants": variants})
    return comparisons


def diagnostic(exc):
    return exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)


def run(args):
    chapters = read_json(args.selection)["chapters"]
    expected_ids = {chapter["chapter_id"] for chapter in chapters}
    pairs = {int(chapter_id): [Path(p) for p in paths] for chapter_id, *paths in args.pair}
    benchmarks = {int(chapter_id): Path(path) for chapter_id, path in args.benchmark}
    if (expected_ids != {133, 600, 273} or len(chapters) != 3
            or any(len(chapter["excerpts"]) != 4 for chapter in chapters)
            or len({e["id"] for c in chapters for e in c["excerpts"]}) != 12):
        raise ValueError("expected the 12 frozen excerpts for chapters 133, 600 and 273")
    if len(pairs) != len(args.pair) or set(pairs) != expected_ids:
        raise ValueError("supply exactly one --pair for each of 133, 600 and 273")
    if args.qualification and (len(benchmarks) != len(args.benchmark) or set(benchmarks) != expected_ids):
        raise ValueError("qualification requires one --benchmark for each of 133, 600 and 273")
    args.output.mkdir(parents=True, exist_ok=True)
    comparisons_path = args.output / "comparisons.json"
    # Suppress a previously published manifest when rechecking this output directory.
    comparisons_path.unlink(missing_ok=True)
    errors, records, jobs, narrator_routes = [], {}, [], set()
    with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for chapter in chapters:
            chapter_id = chapter["chapter_id"]
            status = records[str(chapter_id)] = {}
            try:
                source_words, anchors = source_anchors(db, chapter)
            except (KeyError, OSError, TypeError, ValueError) as exc:
                errors.append(f"chapter {chapter_id}: {diagnostic(exc)}")
                continue
            previous_master, previous_sheet, candidate_master, candidate_sheet = pairs[chapter_id]
            if previous_master.is_file() and candidate_master.is_file() and previous_master.samefile(candidate_master):
                errors.append(f"chapter {chapter_id}: previous and candidate identify the same master")
            for label, master, sidecar in (("previous", previous_master, previous_sheet),
                                           ("candidate", candidate_master, candidate_sheet)):
                context = f"chapter {chapter_id}, {label}"
                try:
                    sheet = read_json(sidecar)
                    edition = status[label] = check_edition(master, sheet, source_words, anchors)
                    duration = edition["duration_seconds"]
                    errors.extend(f"{context}: {err}" for err in edition.pop("errors"))
                    narrator_routes.add(edition["narrator"])
                    if label == "candidate" and args.qualification:
                        if not 480 <= duration <= 600:
                            errors.append(f"{context}: actual duration {duration:.3f} s is outside 480–600 s")
                        wall, failures = check_benchmark(benchmarks[chapter_id], master, chapter, duration, sheet)
                        edition["cold_wall_seconds"] = wall
                        errors.extend(f"{context}: {err}" for err in failures)
                except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
                    errors.append(f"{context}: {diagnostic(exc)}")
            if len(status) != 2:
                continue
            previous, candidate = status["previous"], status["candidate"]
            if previous["narrator_spans"] != candidate["narrator_spans"]:
                errors.append(f"chapter {chapter_id}: the editions assign narration to different source word spans")
            for excerpt_id, spans in anchors.items():
                old = previous["matches"].get(excerpt_id)
                new = candidate["matches"].get(excerpt_id)
                if not old or not new:
                    continue
                if old["spoken_words"] != new["spoken_words"]:
                    errors.append(f"chapter {chapter_id}, {excerpt_id}: spoken copy differs across routes")
                jobs.append((excerpt_id, [role for _, _, role in spans],
                             [("previous", previous_master, old), ("candidate", candidate_master, new)]))
    if len(narrator_routes) != 1:
        errors.append(f"expected one matching narrator reference/renderer across editions, found {sorted(narrator_routes)!r}")
    if not errors:
        try:
            comparisons = generate_comparisons(jobs, args.output)
            comparisons_path.write_text(json.dumps({"comparisons": comparisons}, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
            errors.append(f"matched audio generation: {diagnostic(exc)}")
    result = {"passed": not errors, "qualification": args.qualification,
              "selection": str(args.selection), "chapters": records, "errors": errors}
    report_path = args.output / "qualification-report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path.resolve())
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Run build_listening_pack.py --manifest OUTPUT/comparisons.json --output PACK to blind the clips.",
    )
    parser.add_argument("--selection", type=Path, default=ROOT / "data/benchmarks/qualification-selection.json",
                        help="Frozen source-excerpt manifest")
    parser.add_argument("--db", type=Path, default=ROOT / "src/data/pipeline.db",
                        help="Source chapter database, opened read-only")
    parser.add_argument("--pair", nargs=5, action="append", required=True,
                        metavar=("ID", "PREVIOUS_MASTER", "PREVIOUS_SIDECAR", "CANDIDATE_MASTER", "CANDIDATE_SIDECAR"),
                        help="One paired edition for each DB chapter ID 133, 600 and 273")
    parser.add_argument("--qualification", action="store_true",
                        help="Require candidate durations of 8–10 min and cold runs of at most 40 min")
    parser.add_argument("--benchmark", action="append", nargs=2, default=[], metavar=("ID", "REPORT"),
                        help="Candidate benchmark_chapter.py result.json, required in qualification mode")
    parser.add_argument("--output", type=Path, required=True,
                        help="Directory for qualification-report.json and validated WAV comparisons")
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
