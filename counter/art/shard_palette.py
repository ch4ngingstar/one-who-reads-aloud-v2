"""The 24 colours every sprite is drawn from, and the material ramps built on them.

A material is a (shadow, base, light) triple. Sprites are painted with materials, never
with raw colours, so the lighting pass can shade every surface the same way.
"""
from __future__ import annotations

PALETTE: dict[str, str] = {
    "outline": "#111827",
    "ink": "#222b3b",
    "slate": "#3a4658",
    "stone": "#66758a",
    "steel": "#aab7c7",
    "pale": "#e5edf5",
    "white": "#ffffff",
    "skin": "#f2d2bc",
    "skin_shade": "#d9a88e",
    "tan": "#ad7866",
    "leather_dark": "#704f49",
    "leather": "#725047",
    "auburn": "#9c4a2f",
    "bronze": "#b98a52",
    "gold": "#f1d38a",
    "crimson": "#6e243a",
    "ruby": "#e34b62",
    "violet": "#bda6ff",
    "violet_deep": "#5b4ba8",
    "green_dark": "#246b57",
    "green": "#60c99a",
    "blue_deep": "#155e8a",
    "blue": "#54cae8",
    "ice": "#b8f2f2",
}

# (shadow, base, light) — names from PALETTE
MATERIALS: dict[str, tuple[str, str, str]] = {
    "skin": ("skin_shade", "skin", "skin"),
    "tan": ("leather", "tan", "skin_shade"),
    "black_hair": ("outline", "ink", "slate"),
    "onyx": ("outline", "ink", "slate"),
    "dark_armour": ("ink", "slate", "stone"),
    "stone": ("slate", "stone", "steel"),
    "steel": ("stone", "steel", "pale"),
    "white_cloth": ("steel", "pale", "white"),
    "silver_hair": ("steel", "pale", "white"),
    "gold_hair": ("bronze", "gold", "white"),
    "auburn": ("crimson", "auburn", "bronze"),
    "brown_hair": ("leather_dark", "leather", "bronze"),
    "leather": ("leather_dark", "leather", "bronze"),
    "bronze": ("leather", "bronze", "gold"),
    "green_cloth": ("ink", "green_dark", "green"),
    "blue_cloth": ("ink", "blue_deep", "blue"),
    "ivory": ("steel", "pale", "white"),
    "black_leather": ("outline", "ink", "slate"),
    "shard": ("violet_deep", "violet", "white"),
    "mist": ("blue", "ice", "white"),
    "flame": ("ice", "white", "white"),
    "shadow": ("outline", "ink", "violet_deep"),
    "spell_plate": ("outline", "ink", "slate"),
    "mirror": ("stone", "pale", "white"),
    "wood": ("leather_dark", "leather", "bronze"),
}

# Materials too dark to stand out on GitHub's dark background get a lighter edge.
RIMMED = {"black_hair", "onyx", "black_leather", "shadow", "spell_plate", "dark_armour"}
RIM = {"shadow": "violet", "spell_plate": "violet_deep"}


def rgb(name: str) -> tuple[int, int, int]:
    value = PALETTE[name]
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def palette_rgb() -> set[tuple[int, int, int]]:
    return {rgb(name) for name in PALETTE}
