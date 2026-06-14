"""
Generate docs/screenshots/demo.gif from the three existing UI screenshots.
Produces a looping, labelled slideshow at 1280 px wide with smooth fade transitions.

Usage:  python scripts/make_demo_gif.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "docs" / "screenshots" / "demo.gif"

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_W    = 900           # output width in pixels
HOLD_MS     = 2600          # milliseconds each frame is held
FADE_STEPS  = 8             # number of cross-fade frames between slides
FADE_MS     = 70            # milliseconds per fade frame  (~560 ms total transition)
PALETTE     = 128           # GIF colour depth (max 256; lower = smaller file)

SLIDES = [
    ("docs/screenshots/command-deck.png",          "Command Deck — configure & launch"),
    ("docs/screenshots/live-run.png",              "Live run — chapter progress over SSE"),
    ("docs/screenshots/live-inspector-seeded.png", "Inspector — per-line speaker & emotion"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_and_scale(path: str) -> Image.Image:
    img = Image.open(ROOT / path).convert("RGBA")
    w, h = img.size
    new_h = int(h * TARGET_W / w)
    return img.resize((TARGET_W, new_h), Image.LANCZOS)


def add_label(img: Image.Image, text: str) -> Image.Image:
    out  = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(out)
    pad  = 12
    font_size = max(18, TARGET_W // 60)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rx, ry = pad, out.height - th - pad * 3
    rw, rh = tw + pad * 2, th + pad * 2

    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([rx, ry, rx + rw, ry + rh], radius=6,
                          fill=(15, 15, 15, 200))
    od.text((rx + pad, ry + pad), text, font=font, fill=(220, 220, 220, 255))
    return Image.alpha_composite(out, overlay)


def make_frames() -> list[tuple[Image.Image, int]]:
    """Returns (frame, duration_ms) pairs."""
    slides = [(load_and_scale(p), lbl) for p, lbl in SLIDES]

    # Normalise to the same canvas height (tallest slide)
    max_h = max(img.height for img, _ in slides)
    canvases = []
    for img, lbl in slides:
        canvas = Image.new("RGBA", (TARGET_W, max_h), (20, 20, 20, 255))
        canvas.paste(img, (0, (max_h - img.height) // 2))
        canvases.append((add_label(canvas, lbl), lbl))

    frames: list[tuple[Image.Image, int]] = []

    for i, (cur, _) in enumerate(canvases):
        nxt, _ = canvases[(i + 1) % len(canvases)]

        # Hold the current slide
        frames.append((cur.convert("RGB"), HOLD_MS))

        # Cross-fade into the next
        for step in range(1, FADE_STEPS + 1):
            alpha = step / FADE_STEPS
            blended = Image.blend(cur, nxt, alpha)
            frames.append((blended.convert("RGB"), FADE_MS))

    return frames


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Building demo GIF …")
    frames = make_frames()
    images   = [f for f, _ in frames]
    durations = [d for _, d in frames]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Quantize each frame to PALETTE colours before saving to shrink file size
    quantized = [img.quantize(colors=PALETTE, method=Image.Quantize.MEDIANCUT,
                              dither=Image.Dither.FLOYDSTEINBERG)
                 for img in images]
    quantized[0].save(
        OUT,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_kb = OUT.stat().st_size // 1024
    print(f"Saved {OUT}  ({len(images)} frames, {size_kb} KB)")


if __name__ == "__main__":
    main()
