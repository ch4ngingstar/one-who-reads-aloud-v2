"""
Sound-design cue I/O (Module 3 side-channel, parallel to diarization_io).

Lets a chapter's sound design be authored by Claude (or any cloud LLM / by
hand): export the chapter's deterministic segments, have the model emit a
restrained cinematic cue plan against a FIXED vocabulary, validate it, and
persist it as chapter_cues. Text is never trusted from the model — only the
cue structure is. GPU-free; reuses the cloud-call machinery in diarization_io.

Cue plan shape returned by the model:
  { "sound_design": {
      "scenes": [{"line_start":0,"line_end":14,"ambience_tag":"cold_rain","gain_db":-22}],
      "sfx":    [{"line_index":7,"at":"end","sfx_tag":"sword_clash","gain_db":-12}],
      "music":  [{"line_index":0,"music_tag":"dread_low_drone","gain_db":-20,"duration_s":8}]
  } }
"""
from __future__ import annotations

import json

from diarization_io import (
    segment_chapter,
    ImportRejected,
    CLOUD_PROVIDERS,
    _DEFAULT_MODELS,
    _PROVIDER_CALLS,
)


# ── Fixed cue vocabulary (Shadow Slave themed) ────────────────────────────────
# Claude is prompted against exactly these tags so cues stay on-theme and the
# library has a known, finite set of slots to fill.
CUE_VOCAB: dict[str, list[str]] = {
    "ambience": [
        "dream_realm_void", "nightmare_whispers", "antarctic_wind", "cold_rain",
        "dungeon_drip", "ruined_halls", "forest_night", "market_crowd",
        "tavern_murmur", "open_sea", "storm_surge", "campfire_night",
        "sanctuary_calm",
    ],
    "sfx": [
        "sword_clash", "sword_draw", "shield_block", "arrow_whoosh", "bone_crack",
        "monster_roar", "monster_screech", "flesh_tear", "magic_cast",
        "shadow_whoosh", "rune_activate", "spell_notification", "heartbeat",
        "door_creak", "chains_rattle", "footsteps_stone", "thunder_crack",
        "fire_burst", "water_splash", "crowd_gasp",
    ],
    "music": [
        "dread_low_drone", "sorrow_strings", "tension_rise", "battle_pulse",
        "triumph_swell", "eerie_choir", "mystery_shimmer",
    ],
}

_AMBIENCE = set(CUE_VOCAB["ambience"])
_SFX = set(CUE_VOCAB["sfx"])
_MUSIC = set(CUE_VOCAB["music"])

# Common synonyms the model (or a human) might reach for -> canonical tag. Also
# used at render time (SoundDesigner.resolve_cues) to recover near-misses.
SFX_TAG_ALIASES: dict[str, str] = {
    "rain": "cold_rain", "downpour": "cold_rain", "storm": "storm_surge",
    "wind": "antarctic_wind", "snow": "antarctic_wind", "blizzard": "antarctic_wind",
    "crowd": "market_crowd", "market": "market_crowd", "tavern": "tavern_murmur",
    "dungeon": "dungeon_drip", "cave": "dungeon_drip", "ruins": "ruined_halls",
    "forest": "forest_night", "sea": "open_sea", "ocean": "open_sea",
    "fire": "fire_burst", "campfire": "campfire_night", "void": "dream_realm_void",
    "nightmare": "nightmare_whispers", "system": "spell_notification",
    "sword": "sword_clash", "battle": "battle_pulse", "dread": "dread_low_drone",
    "sorrow": "sorrow_strings", "tension": "tension_rise", "thunder": "thunder_crack",
}

# Conservative per-category default gain (dB) and music length when omitted.
_DEFAULT_GAIN_DB = {"ambience": -22.0, "sfx": -14.0, "music": -20.0}
_GAIN_MIN_DB, _GAIN_MAX_DB = -40.0, 0.0
_MUSIC_MIN_S, _MUSIC_MAX_S, _MUSIC_DEFAULT_S = 1.0, 20.0, 8.0

# A chapter whose cues the user has hand-edited is locked unless force=True.
_REVIEW_LOCK_MSG = (
    "chapter {cid} cues were manually reviewed; pass force=True to overwrite")


# ── Export + prompt ───────────────────────────────────────────────────────────

def build_cue_export(sm, chapter_id: int) -> dict:
    """Read-only payload the cue author (cloud LLM / human) labels."""
    chapter = sm.get_chapter_by_id(chapter_id)
    if chapter is None:
        raise ValueError(f"No chapter with id={chapter_id}")
    segments = segment_chapter(sm, chapter_id)
    return {
        "chapter_id":    chapter_id,
        "chapter_index": chapter["chapter_index"],
        "title":         chapter["title"],
        "vocabulary":    CUE_VOCAB,
        "segments":      [{"i": s["index"], "text": s["text"]} for s in segments],
    }


def build_cue_prompt_text() -> str:
    """System prompt for restrained, cinematic sound-design cue authoring."""
    amb = ", ".join(CUE_VOCAB["ambience"])
    sfx = ", ".join(CUE_VOCAB["sfx"])
    mus = ", ".join(CUE_VOCAB["music"])
    return f"""You are a cinematic sound designer for a dark-fantasy audiobook
("Shadow Slave"). Given a chapter's numbered lines, produce a RESTRAINED sound
design plan. Restraint is the whole point — this must feel like a professional
film/audiobook studio, never cheesy or busy.

PRINCIPLES (follow strictly):
- Ambience beds are the backbone: pick 1-4 scene beds covering contiguous line
  ranges that share a location/mood (e.g. a rainy walk, a dungeon, a battle).
  Beds play quietly UNDER the narration. Cover most of the chapter with beds,
  but switch bed only when the scene/location genuinely changes.
- Discrete SFX are RARE: only for a clear, important on-page event (a sword
  clash, a door, a [System] notification). Aim for 0-6 in a whole chapter. Do
  NOT foley every action. When in doubt, leave it out.
- Music is occasional: 0-2 short swells at a real emotional peak or scene
  transition. Never wall-to-wall music.

You may ONLY use these tags:
  ambience: {amb}
  sfx: {sfx}
  music: {mus}

GAIN: gain_db is negative (quieter). Suggested ranges: ambience -26..-18,
sfx -18..-8, music -24..-16. Beds should sit well below the voice.

OUTPUT: return ONLY a JSON object, no prose:
{{"sound_design": {{
  "scenes": [{{"line_start": int, "line_end": int, "ambience_tag": str, "gain_db": number}}],
  "sfx": [{{"line_index": int, "at": "start"|"end", "sfx_tag": str, "gain_db": number}}],
  "music": [{{"line_index": int, "music_tag": str, "gain_db": number, "duration_s": number}}]
}}}}
Indices refer to the line numbers shown. Scene ranges must be in-bounds and must
not overlap. Omit any array you don't need (but include at least one scene)."""


def _segments_to_user_msg(segments: list) -> str:
    return "\n".join(f"{s['i']}: {s['text']}" for s in segments)


def _parse_sound_design(text: str) -> dict:
    """Extract the {"sound_design": {...}} object from a model's raw text."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ImportRejected("model did not return a JSON sound_design object")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ImportRejected(f"could not parse sound_design JSON: {e}")
    if not isinstance(obj, dict):
        raise ImportRejected("model output is not a JSON object")
    return obj


def format_cues_via_cloud(export_payload: dict, *, provider: str = "claude",
                          api_key: str, model: "str | None" = None,
                          max_tokens: int = 4096) -> dict:
    """Author one chapter's sound design via a cloud LLM.

    `provider` is one of CLOUD_PROVIDERS. Returns the raw ``{"sound_design": …}``
    dict ready for validate_cues / import_cues. Raises ImportRejected (mapped to
    a 4xx by the API) on bad provider / missing key / failed request / unparseable
    output.
    """
    provider = (provider or "claude").strip().lower()
    if provider not in _PROVIDER_CALLS:
        raise ImportRejected(
            f"unknown provider '{provider}' (use one of: {', '.join(CLOUD_PROVIDERS)})")
    if not api_key or not api_key.strip():
        raise ImportRejected("no API key provided")

    segments = export_payload.get("segments", [])
    if not segments:
        raise ImportRejected("export payload has no segments")

    model = (model or "").strip() or _DEFAULT_MODELS[provider]
    system = build_cue_prompt_text()
    user = _segments_to_user_msg(segments)

    try:
        text = _PROVIDER_CALLS[provider](
            system, user, api_key=api_key.strip(), model=model, max_tokens=max_tokens)
    except ImportRejected:
        raise
    except Exception as e:
        raise ImportRejected(f"{provider} request failed: {e}")

    return _parse_sound_design(text)


# ── Validation ────────────────────────────────────────────────────────────────

def _clip_gain(v, category: str) -> float:
    if v is None:
        return _DEFAULT_GAIN_DB[category]
    try:
        return max(_GAIN_MIN_DB, min(_GAIN_MAX_DB, float(v)))
    except (TypeError, ValueError):
        return _DEFAULT_GAIN_DB[category]


def validate_cues(payload: dict, n_segments: int) -> list:
    """Structurally validate a sound_design payload into chapter_cues rows.

    Returns a list of cue dicts for StateManager.replace_chapter_cues. Lenient by
    design (sound design is additive): out-of-range or malformed entries are
    dropped, overlapping scenes are coalesced (later one skipped), gains/durations
    clamped. Raises ImportRejected only when the payload shape is fundamentally
    wrong. Unknown tags are KEPT — they're resolved/skipped at render time.
    """
    if not isinstance(payload, dict):
        raise ImportRejected("sound_design payload must be an object")
    sd = payload.get("sound_design", payload)
    if not isinstance(sd, dict):
        raise ImportRejected("'sound_design' must be an object")

    cues: list = []

    # Scenes — sorted by start, non-overlapping.
    raw_scenes = sd.get("scenes") or []
    if not isinstance(raw_scenes, list):
        raise ImportRejected("'scenes' must be a list")
    accepted = []
    for s in sorted(raw_scenes, key=lambda x: _int_or(x.get("line_start"), 1 << 30)):
        ls, le = _int_or(s.get("line_start")), _int_or(s.get("line_end"))
        tag = s.get("ambience_tag") or s.get("tag")
        if ls is None or le is None or tag is None:
            continue
        if not (0 <= ls <= le < n_segments):
            continue
        if any(ls <= ae and le >= a_s for a_s, ae in accepted):  # overlap -> skip
            continue
        accepted.append((ls, le))
        cues.append({
            "cue_type": "scene", "tag": str(tag), "line_start": ls, "line_end": le,
            "at_anchor": None, "gain_db": _clip_gain(s.get("gain_db"), "ambience"),
            "duration_s": None, "source": "cloud",
        })

    # SFX — anchored to a single line.
    for s in sd.get("sfx") or []:
        li = _int_or(s.get("line_index"))
        tag = s.get("sfx_tag") or s.get("tag")
        if li is None or tag is None or not (0 <= li < n_segments):
            continue
        anchor = s.get("at") or s.get("at_anchor") or "start"
        if anchor not in ("start", "end"):
            anchor = "start"
        cues.append({
            "cue_type": "sfx", "tag": str(tag), "line_start": li, "line_end": None,
            "at_anchor": anchor, "gain_db": _clip_gain(s.get("gain_db"), "sfx"),
            "duration_s": None, "source": "cloud",
        })

    # Music — short swell at a line.
    for m in sd.get("music") or []:
        li = _int_or(m.get("line_index"))
        tag = m.get("music_tag") or m.get("tag")
        if li is None or tag is None or not (0 <= li < n_segments):
            continue
        dur = m.get("duration_s")
        try:
            dur = max(_MUSIC_MIN_S, min(_MUSIC_MAX_S, float(dur)))
        except (TypeError, ValueError):
            dur = _MUSIC_DEFAULT_S
        cues.append({
            "cue_type": "music", "tag": str(tag), "line_start": li, "line_end": None,
            "at_anchor": None, "gain_db": _clip_gain(m.get("gain_db"), "music"),
            "duration_s": dur, "source": "cloud",
        })

    return cues


def _int_or(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ── Import / persist ──────────────────────────────────────────────────────────

def import_cues(sm, chapter_id: int, payload: dict, *, force: bool = False) -> int:
    """Validate a sound_design payload and persist it as the chapter's cues.

    Guards against clobbering manual edits: if the chapter's cues_reviewed flag
    is set, refuses unless force=True. Returns the number of cues written.
    """
    chapter = sm.get_chapter_by_id(chapter_id)
    if chapter is None:
        raise ImportRejected(f"no chapter with id={chapter_id}")
    if not force and chapter.get("cues_reviewed"):
        raise ImportRejected(_REVIEW_LOCK_MSG.format(cid=chapter_id))

    n = len(segment_chapter(sm, chapter_id))
    cues = validate_cues(payload, n)
    sm.replace_chapter_cues(chapter_id, cues)
    return len(cues)
