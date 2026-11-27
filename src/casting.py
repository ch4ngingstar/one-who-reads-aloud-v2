"""Resolve character names and aliases to the same voice in synthesis and QA."""

from dataclasses import dataclass
import re

# ── Speaker alias dictionary ──────────────────────────────────────────────────
# Maps every title / alias the LLM may output → the canonical voice key.
# Keys MUST be in Title Case (matching the .strip().title() normalisation below).
SPEAKER_ALIASES: dict[str, str] = {
    # Sunny & his many titles
    "Sunless":            "Sunny",
    "Lost From Light":    "Sunny",
    "Lord Of Shadows":    "Sunny",
    "Lord Shadow":        "Sunny",
    "The Shopkeeper":     "Sunny",
    "Master Sunless":     "Sunny",
    "Shadow":             "Sunny",
    "Treacherous Shadow": "Sunny",
    "Mongrel":            "Sunny",
    "Devil Of Antarctica":"Sunny",
    "Weaver'S Heir":      "Sunny",   # title() turns ' → 'S

    # The Divine Cohort
    "Neph":               "Nephis",
    "Changing Star":      "Nephis",
    "Light":              "Nephis",
    "Lady Nephis":        "Nephis",
    "Saint Nephis":       "Nephis",

    "Cassia":             "Cassie",
    "Song Of The Fallen": "Cassie",
    "Blind Girl":         "Cassie",
    "Seer":               "Cassie",
    "Saint Cassia":       "Cassie",

    "Athena":             "Effie",
    "Raised By Wolves":   "Effie",
    "Saint Effie":        "Effie",

    "Nightingale":        "Kai",
    "Master Kai":         "Kai",
    "Saint Kai":          "Kai",

    "Soul Reaper":        "Jet",
    "Master Jet":         "Jet",
    "Saint Jet":          "Jet",
    "Boss":               "Jet",

    "Prince Of Nothing":  "Mordret",

    # The Sovereigns & Clan Leaders
    # Titles chain through "Anvil" so a voice cast for Anvil covers them too,
    # while Lord Valor's legacy clip stays the fallback when none is.
    "Anvil":              "Lord Valor",
    "King Anvil":         "Anvil",
    "King Of Swords":     "Anvil",
    "Lord Of Swords":     "Anvil",
    "Anvil Of Valor":     "Anvil",

    "Ki Song":            "Queen Ki Song",
    "Queen Of Beasts":    "Queen Ki Song",
    "Queen Of Song":      "Queen Ki Song",

    # Domain War Saints & Legacies
    "Morgan Of Valor":    "Morgan",
    "Princess Morgan":    "Morgan",
    "Saint Morgan":       "Morgan",

    "Sky Tide":           "Tyris",
    "Saint Tyris":        "Tyris",

    "Saint Roan":         "Roan",

    "Saint Beastmaster":  "Beastmaster",

    "Revel":              "Revel Of Song",
    "Dirge":              "Revel Of Song",
    "Saint Revel":        "Revel Of Song",

    # The Godgrave Cohort
    "Tamar":              "Tamar Of Sorrow",
    "Lady Tamar":         "Tamar Of Sorrow",

    # Lore & Entities
    "Weaver":             "The Nightmare Spell",
    "The Spell":          "The Nightmare Spell",
    "System":             "The Nightmare Spell",
    "Spell":              "The Nightmare Spell",

    "Eurys":              "Eurys Of The Nine",

    # Academy / Past Mentors
    "Ram":                "Instructor Ram",
    "Julius":             "Instructor Ram",
    "Teacher Julius":     "Instructor Ram",

    # NPC Archetypes (LLM fallback tags)
    "Npc_Male":           "The Hardened Awakened",
    "Npc_Female":         "The Bureaucrat",
    "Npc_Noble":          "The Legacy Noble",
    "Npc_Wanderer":       "The Dream Realm Wanderer",
    "Npc_Monster":        "The Nightmare Abomination",
    "Unknown":            "_default",

    # Post-Vol-9 character title variants (canonical names added to DEFAULT_SPEAKERS).
    "Saint Jest":         "Jest",

    # Post-Vol-8 cast (vol9-11). Roster names map to the registered voice keys.
    "Naeve":              "Saint Naeve",
    "Nightwalker":        "Saint Naeve",   # "the Nightwalker" is Naeve's epithet
    "The Nightwalker":    "Saint Naeve",
    "Bloodwave":          "Saint Bloodwave",
    "Detective Sunless":  "Sunny",         # Sunny's undercover identity (vol10 Mirage arc)
    "Sir Sunless":        "Sunny",
    "Princess Moonveil":  "Moonveil",      # epithet -> registered Moonveil clip
    "Warden Of Valor":    "Warden",        # epithet -> registered Warden clip

    # Post-2300 cast with designed voices (2026-11-25).
    "Saint Aether":       "Aether",
    "Uncle Madoc":        "Madoc",
    "Mr. Madoc":          "Madoc",
    "Howl":               "Lonesome Howl",
    "Saint Lonesome Howl": "Lonesome Howl",
    "Chief Bethany":      "Beth",
    "Bethany":            "Beth",
    "Ling":               "Little Ling",
    "Master Quentin":     "Quentin",
    "Awakened Yutra":     "Yutra",
    "Awakened Tegrot":    "Tegrot",
    "Azarax The Mighty":  "Azarax",

    # Corrupted / monster entities
    "Abomination":        "The Nightmare Abomination",
    "Corrupted":          "The Nightmare Abomination",
    "The Abomination":    "The Nightmare Abomination",
    "Monster":            "The Nightmare Abomination",
    "Nightmare Creature": "The Nightmare Abomination",
    "Void Creature":      "The Nightmare Abomination",
    "Corrupted Being":    "The Nightmare Abomination",
    "Shadow Creature":    "The Nightmare Abomination",
    "Hollow":             "The Nightmare Abomination",
    "Corrupted One":      "The Nightmare Abomination",
    "Fallen":             "The Nightmare Abomination",
    "Awakened Monster":   "The Nightmare Abomination",
    "Great Monster":      "The Nightmare Abomination",
    "Creature":           "The Nightmare Abomination",
    "Fiend":              "The Nightmare Abomination",
    "Demon":              "The Nightmare Abomination",
    "Scavenger":          "The Nightmare Abomination",
}



@dataclass(frozen=True)
class VoiceChoice:
    canonical: str
    path: str | None
    fallback: bool


def fallback_key(voices: dict) -> str | None:
    for key in ("_default", "Narrator"):
        if key in voices:
            return key
    return min(voices, default=None)


def voice_path(entry):
    return entry["path"] if isinstance(entry, dict) else entry


def alias_chain(normal: str) -> list[str]:
    """Names from the most specific alias to the final canonical one, e.g. King Anvil → Anvil → Lord Valor."""
    chain = [normal]
    while (nxt := SPEAKER_ALIASES.get(chain[-1])) and nxt not in chain:
        chain.append(nxt)
    return chain


def pool_member(key: str, voices: dict, variant: "int | None") -> str:
    """Pick one voice from a pool ("The Bureaucrat", "The Bureaucrat #2", ...) for `variant`.

    NPC archetypes stand for many different people. A pool gives each chapter its own
    member (variant = chapter id), so the same soldier voice doesn't speak for every
    soldier in the book, while one chapter stays consistent.
    """
    if variant is None:
        return key
    pattern = re.compile(re.escape(key) + r" #\d+", re.I)
    pool = sorted([key] + [k for k in voices if pattern.fullmatch(k)])
    return pool[variant % len(pool)]


def choose_voice(speaker: str, emotion: str, voices: dict, variant: "int | None" = None) -> VoiceChoice:
    chain = alias_chain(speaker.strip().title())
    canonical = chain[-1]
    # The most specific cast name wins (an explicitly cast alias such as Julius
    # beats a legacy shared timbre). Voice keys may have any capitalization.
    by_name = {key.casefold(): key for key in voices}
    for name in chain:
        for candidate in (f"{name}_{emotion}", name):
            key = by_name.get(candidate.casefold())
            if key is not None:
                return VoiceChoice(canonical, voice_path(voices[pool_member(key, voices, variant)]), False)
    key = fallback_key(voices)
    return VoiceChoice(canonical, voice_path(voices[key]) if key else None, True)
