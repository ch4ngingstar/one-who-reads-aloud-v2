"""
Generate docs/screenshots/demo.gif from the three existing UI screenshots.
Each slide is wrapped in a macOS-style browser chrome and placed on a dark
canvas with a soft drop-shadow for a polished product-shot look.

Usage:  python scripts/make_demo_gif.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT  = ROOT / "docs" / "screenshots" / "demo.gif"

# ── Dimensions & timing ───────────────────────────────────────────────────────
CONTENT_W       = 860   # max screenshot width inside chrome
MAX_CONTENT_H   = 620   # all slides are capped/padded to this height
CHROME_H        = 40    # browser title-bar height
CANVAS_PAD      = 28    # padding around chrome frame (gives room for shadow)
HOLD_MS         = 2800  # ms to hold each slide
FADE_STEPS      = 10    # cross-fade frames between slides
FADE_MS         = 55    # ms per fade frame
PALETTE         = 192   # GIF colour depth (max 256)

# ── Colours ───────────────────────────────────────────────────────────────────
BG_COLOR    = (10, 10, 10)
CHROME_BG   = (24, 24, 24)
SEPARATOR   = (44, 44, 44)
DOT_RED     = (255,  96,  92)
DOT_YELLOW  = (255, 189,  68)
DOT_GREEN   = ( 40, 201,  64)
URL_BG      = (42, 42, 42)
URL_FG      = (150, 150, 150)
LABEL_BG    = (12, 12, 12, 215)
LABEL_FG    = (215, 215, 215, 255)

SLIDES = [
    # (path,  caption,  crop_fractions or None)
    # crop_fractions: (left, top, right, bottom) as fraction of original dims
    (
        "docs/screenshots/command-deck.png",
        "Command Deck — configure & launch",
        None,
    ),
    (
        "docs/screenshots/live-run.png",
        "Live run — chapter progress over SSE",
        # Trim browser chrome (top ~9%) and show just the app content
        (0.0, 0.09, 1.0, 0.72),
    ),
    (
        "docs/screenshots/live-inspector-seeded.png",
        "Inspector — per-line speaker & emotion",
        # Same browser chrome trim; inspector panel is fully visible in top 65%
        (0.0, 0.04, 1.0, 0.70),
    ),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_slide(path: str, crop: tuple | None) -> Image.Image:
    """Load, crop, fit width, then normalise to CONTENT_W × MAX_CONTENT_H."""
    img = Image.open(ROOT / path).convert("RGB")
    if crop:
        w, h = img.size
        box  = (int(crop[0]*w), int(crop[1]*h), int(crop[2]*w), int(crop[3]*h))
        img  = img.crop(box)

    iw, ih = img.size
    if iw > CONTENT_W:
        img = img.resize((CONTENT_W, int(ih * CONTENT_W / iw)), Image.LANCZOS)

    # Centre-pad narrower screenshots horizontally
    if img.width < CONTENT_W:
        pad = Image.new("RGB", (CONTENT_W, img.height), CHROME_BG)
        pad.paste(img, ((CONTENT_W - img.width) // 2, 0))
        img = pad

    cw, ch = img.size
    if ch > MAX_CONTENT_H:
        # Crop — always show from the top (header + content visible)
        img = img.crop((0, 0, cw, MAX_CONTENT_H))
    elif ch < MAX_CONTENT_H:
        # Pad bottom with app background (dark — blends naturally)
        pad = Image.new("RGB", (cw, MAX_CONTENT_H), BG_COLOR)
        pad.paste(img, (0, 0))
        img = pad

    return img  # guaranteed CONTENT_W × MAX_CONTENT_H


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def add_chrome(content: Image.Image) -> Image.Image:
    """Wrap content with a dark macOS-style browser title bar."""
    cw, ch = content.size
    frame  = Image.new("RGB", (cw, CHROME_H + ch), CHROME_BG)
    draw   = ImageDraw.Draw(frame)

    # Traffic-light dots
    dot_y = CHROME_H // 2
    for i, col in enumerate([DOT_RED, DOT_YELLOW, DOT_GREEN]):
        cx = 16 + i * 20
        draw.ellipse([cx-6, dot_y-6, cx+6, dot_y+6], fill=col)

    # URL bar
    bar_x1, bar_y1 = 72, 7
    bar_x2, bar_y2 = cw - 14, CHROME_H - 7
    draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=5, fill=URL_BG)

    font = _font(11)
    url  = "localhost:3000"
    bbox = draw.textbbox((0, 0), url, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    tx = bar_x1 + (bar_x2 - bar_x1 - tw) // 2
    ty = bar_y1 + (bar_y2 - bar_y1 - th) // 2
    draw.text((tx, ty), url, font=font, fill=URL_FG)

    draw.line([(0, CHROME_H-1), (cw, CHROME_H-1)], fill=SEPARATOR)
    frame.paste(content, (0, CHROME_H))
    return frame


def add_label(img: Image.Image, text: str) -> Image.Image:
    out  = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(out)
    font = _font(13)
    pad  = 10

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    rx, ry = pad, out.height - th - pad * 3
    rw, rh = tw + pad*2, th + pad*2

    ov = Image.new("RGBA", out.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle([rx, ry, rx+rw, ry+rh], radius=5, fill=LABEL_BG)
    od.text((rx+pad, ry+pad), text, font=font, fill=LABEL_FG)
    return Image.alpha_composite(out, ov)


def on_canvas(frame: Image.Image) -> Image.Image:
    """Place chrome'd frame on dark canvas with a soft drop-shadow."""
    fw, fh = frame.size
    cw = fw + CANVAS_PAD * 2
    ch = fh + CANVAS_PAD * 2

    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle(
        [CANVAS_PAD+5, CANVAS_PAD+8, CANVAS_PAD+fw+5, CANVAS_PAD+fh+8],
        fill=(0, 0, 0, 170),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=12))

    canvas = Image.new("RGBA", (cw, ch), (*BG_COLOR, 255))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(frame.convert("RGBA"), (CANVAS_PAD, CANVAS_PAD))
    return canvas.convert("RGB")


def make_frames() -> list[tuple[Image.Image, int]]:
    slides = []
    for path, label, crop in SLIDES:
        content  = load_slide(path, crop)
        chromed  = add_chrome(content)
        labelled = add_label(chromed.convert("RGBA"), label).convert("RGB")
        final    = on_canvas(labelled)
        slides.append(final)
        print(f"  {Path(path).name}: {final.size}")

    # All slides are now identical size — no padding step needed
    assert len({s.size for s in slides}) == 1, "slides must be the same size"

    frames: list[tuple[Image.Image, int]] = []
    for i, cur in enumerate(slides):
        nxt = slides[(i + 1) % len(slides)]
        frames.append((cur, HOLD_MS))
        for step in range(1, FADE_STEPS + 1):
            frames.append((Image.blend(cur, nxt, step / FADE_STEPS), FADE_MS))

    return frames


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Building demo GIF …")
    frames    = make_frames()
    images    = [f for f, _ in frames]
    durations = [d for _, d in frames]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    quantized = [
        img.quantize(colors=PALETTE, method=Image.Quantize.MEDIANCUT,
                     dither=Image.Dither.FLOYDSTEINBERG)
        for img in images
    ]
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
