"""Quality gates for the soul-shard counter art (counter/DESIGN.md §5).

Run: python -m pytest tests/test_counter_art.py
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

ART = Path(__file__).resolve().parent.parent / "counter" / "art"
sys.path.insert(0, str(ART))

# Loaded under a unique name: plain "build" could resolve to an installed package.
_spec = importlib.util.spec_from_file_location("shard_build", ART / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

from shard_cast import CAST  # noqa: E402
from shard_kit import CAPTION_FONT, DIGIT_FONT, H, SHARD, SHARD_X, SHARD_Y, W, Canvas, draw_shard  # noqa: E402
from shard_palette import MATERIALS, PALETTE, palette_rgb, rgb  # noqa: E402


@pytest.fixture(scope="module")
def sprites() -> "dict[str, Image.Image]":
    return build.build(check=True)


def test_palette_has_24_unique_colours():
    assert len(PALETTE) == 24
    assert len(palette_rgb()) == 24


def test_materials_only_use_palette_names():
    for name, ramp in MATERIALS.items():
        assert len(ramp) == 3, name
        assert all(colour in PALETTE for colour in ramp), name


def test_cast_covers_every_digit():
    assert sorted(CAST) == [str(d) for d in range(10)]


def test_every_sprite_passes_validation(sprites):
    assert len(sprites) == 10
    for digit, img in sprites.items():
        assert img.size == (W, H), digit


def test_validation_rejects_off_palette_pixel(sprites):
    img = sprites["1"].copy()
    img.putpixel((20, 50), (1, 2, 3, 255))
    with pytest.raises(build.ArtError, match="off-palette"):
        build.validate("1", img)


def test_validation_rejects_missing_shard():
    cv = Canvas()
    cv.rect(10, 40, 20, 60, "steel")
    with pytest.raises(build.ArtError, match="soul shard"):
        build.validate("x", cv.render())


def test_digit_sits_at_the_same_pixels_in_every_sprite(sprites):
    """The numeral is the one thing a reader must find instantly, so it never moves."""
    ink = rgb("outline")
    for digit, img in sprites.items():
        if digit == "0":
            continue  # the Spell's empty socket carves its numeral in violet
        for dy, row in enumerate(DIGIT_FONT[digit]):
            for dx, ch in enumerate(row):
                if ch == "#":
                    assert img.getpixel((SHARD_X + 3 + dx, SHARD_Y + 7 + dy))[:3] == ink, digit


def test_shard_is_identical_outside_the_numeral(sprites):
    reference = Canvas()
    draw_shard(reference, "8")
    ref = reference.render()
    for digit, img in sprites.items():
        if digit == "0":
            continue
        for dy, row in enumerate(SHARD):
            for dx, ch in enumerate(row):
                x, y = SHARD_X + dx, SHARD_Y + dy
                inside_numeral = 3 <= dx < 10 and 7 <= dy < 18
                if ch != "." and not inside_numeral:
                    assert img.getpixel((x, y)) == ref.getpixel((x, y)), (digit, x, y)


def test_generated_typescript_matches_the_sprites(sprites):
    source = build.GENERATED.read_text(encoding="utf-8")
    assert "do not edit by hand" in source
    assert f"export const SPRITE_W = {W};" in source and f"export const SPRITE_H = {H};" in source
    digits = dict(re.findall(r'^  "(\d)": "([A-Za-z0-9+/=]+)"', source, flags=re.M))
    assert sorted(digits) == [str(d) for d in range(10)]
    for digit, data in digits.items():
        decoded = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")
        assert decoded.tobytes() == sprites[digit].tobytes(), \
            f"sprites.generated.ts is stale for {digit}: run python counter/art/build.py"


def test_generated_font_covers_the_caption():
    source = build.GENERATED.read_text(encoding="utf-8")
    for ch in "[ ],0123456789souls have heard this story":
        assert ch in CAPTION_FONT, ch
        assert f"    {json.dumps(ch)}: " in source, ch
    for ch, rows in CAPTION_FONT.items():
        assert len(rows) == 7 and all(len(r) == 5 and set(r) <= {"#", "."} for r in rows), ch


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
