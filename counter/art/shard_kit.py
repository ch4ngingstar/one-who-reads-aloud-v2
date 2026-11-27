"""The pixel kit: a 48x96 canvas painted with materials, then lit and outlined in one pass.

Why materials: ten characters drawn by hand drift apart in style. Painting with
materials and letting one lighting pass shade every surface (light from the top-left)
keeps the whole cast in the same light, with the same 1 px outline and the same rim on
dark armour, so the counter reads as one set.
"""
from __future__ import annotations

from PIL import Image

from shard_palette import MATERIALS, RIM, RIMMED, rgb

W, H = 48, 96
SHARD_X, SHARD_Y = 27, 6          # every shard is drawn here, so digits line up across sprites
SHARD_W, SHARD_H = 15, 22


class Canvas:
    def __init__(self, w: int = W, h: int = H):
        self.w, self.h = w, h
        self.mat: list[list[str | None]] = [[None] * w for _ in range(h)]
        self.flat: list[list[str | None]] = [[None] * w for _ in range(h)]

    # ── primitives ─────────────────────────────────────────────────────────
    def px(self, x: int, y: int, mat: str) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.mat[y][x] = mat
            self.flat[y][x] = None

    def dot(self, x: int, y: int, colour: str) -> None:
        """A detail pixel in a fixed palette colour (eyes, glints); never shaded."""
        if 0 <= x < self.w and 0 <= y < self.h:
            self.flat[y][x] = colour
            if self.mat[y][x] is None:
                self.mat[y][x] = "__flat__"

    def erase(self, x: int, y: int) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.mat[y][x] = None
            self.flat[y][x] = None

    def rect(self, x0: int, y0: int, x1: int, y1: int, mat: str) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, mat)

    def line(self, x0: int, y0: int, x1: int, y1: int, mat: str, width: int = 1) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            for ox in range(width):
                for oy in range(width):
                    self.px(x0 + ox - width // 2, y0 + oy - width // 2, mat)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, mat: str) -> None:
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                    self.px(x, y, mat)

    def poly(self, points: "list[tuple[float, float]]", mat: str) -> None:
        """Scanline fill of a closed polygon (pixel centres)."""
        ys = [p[1] for p in points]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            yc = y + 0.5
            xs = []
            for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
                if (y1 <= yc < y2) or (y2 <= yc < y1):
                    xs.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                for x in range(int(round(a)), int(round(b))):
                    self.px(x, y, mat)

    # ── rendering ──────────────────────────────────────────────────────────
    def _same(self, x: int, y: int, mat: str) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and self.mat[y][x] == mat

    def _opaque(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and self.mat[y][x] is not None

    def render(self) -> Image.Image:
        # Keep a 1 px transparent border so the outline can always close around the figure.
        for x in range(self.w):
            self.erase(x, 0)
            self.erase(x, self.h - 1)
        for y in range(self.h):
            self.erase(0, y)
            self.erase(self.w - 1, y)
        img = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        out = img.load()
        for y in range(self.h):
            for x in range(self.w):
                mat = self.mat[y][x]
                if mat is None:
                    # Outline: a transparent pixel touching the silhouette (4-neighbours).
                    if any(self._opaque(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                        out[x, y] = (*rgb("outline"), 255)
                    continue
                if self.flat[y][x]:
                    out[x, y] = (*rgb(self.flat[y][x]), 255)
                    continue
                shadow, base, light = MATERIALS[mat]
                colour = base
                outside = [not self._opaque(x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
                if mat in RIMMED and any(outside):
                    colour = RIM.get(mat, light)          # dark armour keeps a visible edge
                elif not self._same(x - 1, y, mat) or not self._same(x, y - 1, mat):
                    colour = light                         # faces the light (top-left)
                elif (not self._same(x + 1, y, mat) or not self._same(x, y + 1, mat)
                      or not self._same(x + 2, y, mat)):
                    colour = shadow                        # a 2 px band on the far side gives volume
                out[x, y] = (*rgb(colour), 255)
        return img


def stamp(cv: Canvas, x0: int, y0: int, rows: "list[str]", legend: "dict[str, tuple[str, str]]") -> None:
    """Draw a text pixel map. legend: char -> ('mat', name) | ('flat', colour) | ('erase', '')."""
    for dy, row in enumerate(rows):
        for dx, ch in enumerate(row):
            if ch == "." or ch not in legend:
                continue
            kind, name = legend[ch]
            if kind == "mat":
                cv.px(x0 + dx, y0 + dy, name)
            elif kind == "flat":
                cv.dot(x0 + dx, y0 + dy, name)
            else:
                cv.erase(x0 + dx, y0 + dy)


# ── The soul shard ────────────────────────────────────────────────────────────
SHARD = [
    ".......#.......",
    "......#W#......",
    ".....#WPV#.....",
    "....#WPPVV#....",
    "...#WPPPPVV#...",
    "..#WPPPPPPVV#..",
    ".#WPPPPPPPPVV#.",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    "#WPPPPPPPPPPVV#",
    ".#VPPPPPPPPVD#.",
    "..#VVPPPPVVD#..",
    "...#DDVVVDD#...",
    "....#######....",
]
SHARD_LEGEND = {"#": ("flat", "outline"), "W": ("flat", "white"), "P": ("flat", "pale"),
                "V": ("flat", "violet"), "D": ("flat", "violet_deep")}

DIGIT_FONT: dict[str, list[str]] = {
    "0": ["..###..", ".##.##.", "##...##", "##...##", "##...##", "##...##", "##...##", "##...##", "##...##", ".##.##.", "..###.."],
    "1": ["...##..", "..###..", ".####..", "...##..", "...##..", "...##..", "...##..", "...##..", "...##..", "...##..", ".######"],
    "2": [".#####.", "##...##", ".....##", ".....##", "....##.", "...##..", "..##...", ".##....", "##.....", "##.....", "#######"],
    "3": [".#####.", "##...##", ".....##", ".....##", "..####.", ".....##", ".....##", ".....##", ".....##", "##...##", ".#####."],
    "4": ["....##.", "...###.", "..####.", ".##.##.", "##..##.", "##..##.", "#######", "....##.", "....##.", "....##.", "....##."],
    "5": ["#######", "##.....", "##.....", "######.", ".....##", ".....##", ".....##", ".....##", ".....##", "##...##", ".#####."],
    "6": ["..####.", ".##....", "##.....", "##.....", "######.", "##...##", "##...##", "##...##", "##...##", "##...##", ".#####."],
    "7": ["#######", ".....##", ".....##", "....##.", "....##.", "...##..", "...##..", "..##...", "..##...", "..##...", "..##..."],
    "8": [".#####.", "##...##", "##...##", "##...##", ".#####.", "##...##", "##...##", "##...##", "##...##", "##...##", ".#####."],
    "9": [".#####.", "##...##", "##...##", "##...##", "##...##", ".######", ".....##", ".....##", ".....##", "....##.", ".####.."],
}


def draw_shard(cv: Canvas, digit: str, x: int = SHARD_X, y: int = SHARD_Y) -> None:
    """The one soul shard: the same pixels in every sprite, digit carved at the same spot."""
    stamp(cv, x, y, SHARD, SHARD_LEGEND)
    glyph = DIGIT_FONT[digit]
    for dy, row in enumerate(glyph):
        for dx, ch in enumerate(row):
            if ch == "#":
                cv.dot(x + 3 + dx, y + 7 + dy, "outline")


# ── Caption font (5x7), exported to the Worker ───────────────────────────────
CAPTION_FONT: dict[str, list[str]] = {
    " ": ["....."] * 7,
    "[": ["###..", "#....", "#....", "#....", "#....", "#....", "###.."],
    "]": ["..###", "....#", "....#", "....#", "....#", "....#", "..###"],
    ",": [".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["####.", "....#", "....#", ".###.", "....#", "....#", "####."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
    "a": [".....", ".....", ".###.", "....#", ".####", "#...#", ".####"],
    "d": ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###."],
    "h": ["#....", "#....", "####.", "#...#", "#...#", "#...#", "#...#"],
    "i": ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."],
    "l": [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "o": [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."],
    "r": [".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."],
    "s": [".....", ".....", ".####", "#....", ".###.", "....#", "####."],
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#..#", "..##."],
    "u": [".....", ".....", "#...#", "#...#", "#...#", "#..##", ".##.#"],
    "v": [".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "y": [".....", ".....", "#...#", "#...#", ".####", "....#", ".###."],
}
