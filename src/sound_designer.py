"""
Module 5b: Sound Designer
=========================
Layers cinematic sound design (ambience beds, sparse SFX, occasional music)
under an assembled voice track and mixes them with sidechain ducking.

CPU-ONLY — runs inside the assembly stage, AFTER the LLM and TTS models are
unloaded from VRAM. Adds zero VRAM cost.

Design (two-pass render, driven by AudioAssembler):
  Pass 1 (AudioAssembler): concat per-line WAVs + silence -> voice_bus.wav, and
          build an exact timeline {line_index: (start_ms, end_ms)} from the same
          WAV durations + silence gaps that were concatenated.
  Pass 2 (here): lay ambience/music under the voice, duck them beneath it via
          sidechaincompress, place discrete SFX at line offsets, mix, encode.

Robustness contract — sound design is strictly ADDITIVE and may never fail a
chapter:
  * a cue whose clip is missing, or that points at a line not in the timeline,
    is dropped with a warning (resolve_cues).
  * any FFmpeg failure in pass 2 falls back to encoding the plain voice bus
    (render -> _encode_plain).

REQUIREMENT: FFmpeg must be in PATH (same as AudioAssembler).
"""

import subprocess
import wave
from pathlib import Path

from state_manager import _resolve_stored_path


# ── Config defaults ───────────────────────────────────────────────────────────
_DEFAULT_SD_CFG = {
    "output_sample_rate": 44100,
    "output_format":      "mp3",
    "mp3_bitrate":        "320k",

    # Sidechain ducking — ambience/music bed ducks under the voice key.
    # release too short -> audible pumping; these are conservative, tune by ear.
    "duck_threshold": 0.05,
    "duck_ratio":     6,
    "duck_attack":    15,    # ms
    "duck_release":   300,   # ms
    "duck_makeup":    1,

    # Fades (seconds) at scene/music edges so loops and entries are seamless.
    "scene_fade_in_s":  1.2,
    "scene_fade_out_s": 1.5,
    "music_fade_in_s":  1.5,
    "music_fade_out_s": 2.0,
    "sfx_fade_in_s":    0.03,

    # Final brickwall so layered material can never clip.
    "limiter_limit": 0.95,
}

# Conservative per-category gain (dB) when a cue omits gain_db.
_DEFAULT_GAIN_DB = {"ambience": -22.0, "music": -20.0, "sfx": -14.0}

# Clip gains to a sane range regardless of source.
_GAIN_MIN_DB, _GAIN_MAX_DB = -40.0, 0.0
# Music swell length bounds (seconds).
_MUSIC_MIN_S, _MUSIC_MAX_S = 1.0, 20.0


class SoundDesigner:
    """Builds the pass-2 mix timeline + FFmpeg filter graph and renders it."""

    def __init__(self, cfg: "dict | None" = None):
        self.cfg = {**_DEFAULT_SD_CFG, **(cfg or {})}

    # ── Timeline ──────────────────────────────────────────────────────────────

    @staticmethod
    def _wav_duration_ms(wav_path: Path) -> float:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate() * 1000.0

    def build_timeline(
        self,
        sorted_lines: list,
        inter_line_silence_ms: int,
        inter_speaker_silence_ms: int,
    ) -> "tuple[dict[int, tuple[float, float]], float]":
        """Compute {line_index: (start_ms, end_ms)} matching the concat order.

        Must mirror AudioAssembler._build_concat_list EXACTLY: a gap precedes
        every line after the first, longer when the speaker changes. Only the
        lines actually concatenated (tts_done with a readable WAV) appear in the
        timeline; cues at any other index are skipped downstream.

        Returns (timeline, total_ms).
        """
        timeline: dict[int, tuple[float, float]] = {}
        cursor = 0.0
        for i, line in enumerate(sorted_lines):
            if i > 0:
                prev = sorted_lines[i - 1]
                cursor += (
                    inter_speaker_silence_ms
                    if prev["speaker"] != line["speaker"]
                    else inter_line_silence_ms
                )
            wav = _resolve_stored_path(line["audio_path"]).resolve()
            dur = self._wav_duration_ms(wav)
            start = cursor
            cursor += dur
            timeline[line["line_index"]] = (start, cursor)
        return timeline, cursor

    # ── Cue resolution ────────────────────────────────────────────────────────

    @staticmethod
    def _clip_gain(gain_db, category: str) -> float:
        if gain_db is None:
            return _DEFAULT_GAIN_DB.get(category, -20.0)
        return max(_GAIN_MIN_DB, min(_GAIN_MAX_DB, float(gain_db)))

    def _resolve_tag(self, tag: str, sfx_map: dict, alias_map: dict) -> "str | None":
        if tag in sfx_map:
            return tag
        aliased = (alias_map or {}).get(tag)
        if aliased and aliased in sfx_map:
            return aliased
        return None

    def resolve_cues(
        self,
        cues: list,
        sfx_map: dict,
        timeline: dict,
        alias_map: "dict | None" = None,
    ) -> list:
        """Turn stored cue rows into concrete, render-ready items.

        Drops (with a printed warning) any cue whose tag can't be resolved to a
        library clip, or whose line anchor isn't in the timeline. The result is
        a list of dicts ordered ambience -> music -> sfx (input order), each:
          ambience: {kind, path, loopable, start_ms, dur_s, gain_db}
          music:    {kind, path, at_ms, dur_s, gain_db}
          sfx:      {kind, path, at_ms, gain_db}
        """
        scenes, musics, sfxs = [], [], []
        for c in cues:
            tag = self._resolve_tag(c["tag"], sfx_map, alias_map)
            if tag is None:
                print(f"[sound] skip cue: unknown tag '{c['tag']}' "
                      f"(not in library)")
                continue
            asset = sfx_map[tag]
            path = _resolve_stored_path(asset["path"]).resolve()
            if not path.exists():
                print(f"[sound] skip cue: clip missing for '{tag}' ({path})")
                continue

            ctype = c["cue_type"]
            if ctype == "scene":
                item = self._resolve_scene(c, path, asset, timeline)
                if item:
                    scenes.append(item)
            elif ctype == "music":
                item = self._resolve_music(c, path, timeline)
                if item:
                    musics.append(item)
            elif ctype == "sfx":
                item = self._resolve_sfx(c, path, timeline)
                if item:
                    sfxs.append(item)
            else:
                print(f"[sound] skip cue: unknown cue_type '{ctype}'")

        return scenes + musics + sfxs

    def _resolve_scene(self, c, path, asset, timeline):
        start_idx = c["line_start"]
        end_idx = c.get("line_end")
        if start_idx not in timeline:
            print(f"[sound] skip scene '{c['tag']}': start line "
                  f"{start_idx} not synthesised")
            return None
        start_ms = timeline[start_idx][0]
        if end_idx is None:
            end_idx = start_idx
        if end_idx in timeline:
            end_ms = timeline[end_idx][1]
        else:  # clamp to the last synthesised line within the range
            below = [k for k in timeline if k <= end_idx]
            if not below:
                return None
            end_ms = timeline[max(below)][1]
        dur_s = (end_ms - start_ms) / 1000.0
        if dur_s <= 0:
            return None
        return {
            "kind": "ambience",
            "path": path,
            "loopable": bool(asset.get("loopable", True)),
            "start_ms": int(round(start_ms)),
            "dur_s": dur_s,
            "gain_db": self._clip_gain(c.get("gain_db"), "ambience"),
        }

    def _resolve_music(self, c, path, timeline):
        idx = c["line_start"]
        if idx not in timeline:
            print(f"[sound] skip music '{c['tag']}': line "
                  f"{idx} not synthesised")
            return None
        dur_s = c.get("duration_s") or 8.0
        dur_s = max(_MUSIC_MIN_S, min(_MUSIC_MAX_S, float(dur_s)))
        return {
            "kind": "music",
            "path": path,
            "at_ms": int(round(timeline[idx][0])),
            "dur_s": dur_s,
            "gain_db": self._clip_gain(c.get("gain_db"), "music"),
        }

    def _resolve_sfx(self, c, path, timeline):
        idx = c["line_start"]
        if idx not in timeline:
            print(f"[sound] skip sfx '{c['tag']}': line "
                  f"{idx} not synthesised")
            return None
        anchor = c.get("at_anchor") or "start"
        at_ms = timeline[idx][1] if anchor == "end" else timeline[idx][0]
        return {
            "kind": "sfx",
            "path": path,
            "at_ms": int(round(at_ms)),
            "gain_db": self._clip_gain(c.get("gain_db"), "sfx"),
        }

    # ── Filter graph ──────────────────────────────────────────────────────────

    def _delays(self, at_ms: int, n_channels: int) -> str:
        """adelay value: one delay per channel, pipe-separated."""
        return "|".join([str(int(at_ms))] * n_channels)

    def _layout(self, n_channels: int) -> str:
        return "stereo" if n_channels == 2 else "mono"

    def build_filter_complex(
        self,
        resolved: list,
        n_channels: int,
    ) -> "tuple[list[list[str]], str]":
        """Build (extra_inputs, filter_complex) for the pass-2 mix.

        Input 0 is always the caller's voice bus; the returned ``extra_inputs``
        are the cue clips (ffmpeg ``-i`` arg lists) starting at input index 1, in
        the same order as ``resolved``. The graph references them as [1:a], [2:a]…
        and produces a single ``[mix]`` output. Pure + side-effect free so it can
        be unit-tested by asserting on the returned string.
        """
        cfg = self.cfg
        sr = cfg["output_sample_rate"]
        layout = self._layout(n_channels)
        fmt = f"aformat=sample_rates={sr}:channel_layouts={layout}"

        inputs: list[list[str]] = []
        chains: list[str] = []
        bed_labels: list[str] = []
        sfx_labels: list[str] = []

        idx = 1  # 0 is the voice bus
        for item in resolved:
            kind = item["kind"]
            gain = item["gain_db"]
            if kind == "ambience":
                # Loop a short bed to fill the scene; trim+fade to its length.
                loop = ["-stream_loop", "-1"] if item["loopable"] else []
                inputs.append([*loop, "-i", str(item["path"])])
                d = item["dur_s"]
                fo = cfg["scene_fade_out_s"]
                fo_st = max(0.0, d - fo)
                lbl = f"amb{idx}"
                chains.append(
                    f"[{idx}:a]atrim=0:{d:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:st=0:d={cfg['scene_fade_in_s']},"
                    f"afade=t=out:st={fo_st:.3f}:d={fo},"
                    f"volume={gain}dB,{fmt},"
                    f"adelay={self._delays(item['start_ms'], n_channels)}[{lbl}]"
                )
                bed_labels.append(lbl)
                idx += 1
            elif kind == "music":
                inputs.append(["-i", str(item["path"])])
                d = item["dur_s"]
                fo = cfg["music_fade_out_s"]
                fo_st = max(0.0, d - fo)
                lbl = f"mus{idx}"
                chains.append(
                    f"[{idx}:a]atrim=0:{d:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:st=0:d={cfg['music_fade_in_s']},"
                    f"afade=t=out:st={fo_st:.3f}:d={fo},"
                    f"volume={gain}dB,{fmt},"
                    f"adelay={self._delays(item['at_ms'], n_channels)}[{lbl}]"
                )
                bed_labels.append(lbl)
                idx += 1
            elif kind == "sfx":
                inputs.append(["-i", str(item["path"])])
                lbl = f"sfx{idx}"
                chains.append(
                    f"[{idx}:a]volume={gain}dB,"
                    f"afade=t=in:st=0:d={cfg['sfx_fade_in_s']},{fmt},"
                    f"adelay={self._delays(item['at_ms'], n_channels)}[{lbl}]"
                )
                sfx_labels.append(lbl)
                idx += 1

        graph = list(chains)

        # Assemble the buses. Ambience+music form one ducked bed; SFX punch
        # through (kept out of the duck, they're sparse and intentional).
        if bed_labels:
            graph.append("[0:a]asplit=2[vmain][vkey]")
            bed_in = "".join(f"[{l}]" for l in bed_labels)
            graph.append(
                f"{bed_in}amix=inputs={len(bed_labels)}:normalize=0[bedraw]"
            )
            graph.append(
                f"[bedraw][vkey]sidechaincompress="
                f"threshold={cfg['duck_threshold']}:ratio={cfg['duck_ratio']}:"
                f"attack={cfg['duck_attack']}:release={cfg['duck_release']}:"
                f"makeup={cfg['duck_makeup']}[bedduck]"
            )
            final_labels = ["[vmain]", "[bedduck]"]
        else:
            final_labels = ["[0:a]"]

        if sfx_labels:
            sfx_in = "".join(f"[{l}]" for l in sfx_labels)
            graph.append(
                f"{sfx_in}amix=inputs={len(sfx_labels)}:normalize=0[sfxbus]"
            )
            final_labels.append("[sfxbus]")

        # normalize=0 is CRITICAL: amix's default divides by N and would crush
        # the voice. Per-stream volume + a final limiter control levels instead.
        if len(final_labels) == 1:
            graph.append(f"{final_labels[0]}alimiter=limit={cfg['limiter_limit']}[mix]")
        else:
            fin = "".join(final_labels)
            graph.append(
                f"{fin}amix=inputs={len(final_labels)}:normalize=0[premix]"
            )
            graph.append(f"[premix]alimiter=limit={cfg['limiter_limit']}[mix]")

        return inputs, ";".join(graph)

    # ── Render ────────────────────────────────────────────────────────────────

    def render(
        self,
        voice_wav: "str | Path",
        resolved: list,
        out_path: "str | Path",
        n_channels: int = 2,
    ) -> str:
        """Mix the voice bus with resolved cues into out_path.

        Falls back to encoding the plain voice bus if there are no cues to mix
        or if FFmpeg fails for any reason — sound design can never fail a chapter.
        Returns the output path.
        """
        voice_wav = Path(voice_wav)
        out_path = Path(out_path)

        if not resolved:
            return self._encode_plain(voice_wav, out_path, n_channels)

        inputs, graph = self.build_filter_complex(resolved, n_channels)
        cmd = ["ffmpeg", "-y", "-i", str(voice_wav)]
        for inp in inputs:
            cmd += inp
        cmd += ["-filter_complex", graph, "-map", "[mix]",
                "-ar", str(self.cfg["output_sample_rate"]), "-ac", str(n_channels)]
        if self.cfg["output_format"] == "mp3":
            cmd += ["-b:a", self.cfg["mp3_bitrate"]]
        cmd.append(str(out_path))

        try:
            self._run(cmd)
            if out_path.exists() and out_path.stat().st_size >= 4096:
                return str(out_path)
            print("[sound] WARNING: mix produced no/empty output; "
                  "falling back to plain voice.")
        except Exception as e:  # any ffmpeg/graph error must not fail the chapter
            print(f"[sound] WARNING: mix failed ({e}); "
                  "falling back to plain voice.")

        return self._encode_plain(voice_wav, out_path, n_channels)

    def _encode_plain(self, voice_wav: Path, out_path: Path, n_channels: int) -> str:
        """Encode the voice bus straight to the output format (no sound design)."""
        cmd = ["ffmpeg", "-y", "-i", str(voice_wav),
               "-ar", str(self.cfg["output_sample_rate"]), "-ac", str(n_channels)]
        if self.cfg["output_format"] == "mp3":
            cmd += ["-b:a", self.cfg["mp3_bitrate"]]
        cmd.append(str(out_path))
        self._run(cmd)
        return str(out_path)

    @staticmethod
    def _run(cmd: list) -> None:
        """Execute an FFmpeg command. Monkeypatched out in unit tests."""
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (exit {result.returncode}):\n{result.stderr[-1000:]}"
            )
