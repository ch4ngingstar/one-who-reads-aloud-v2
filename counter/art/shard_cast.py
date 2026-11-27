"""The ten counter characters, each holding the soul shard for one digit (DESIGN.md §2).

Shared skeleton (4 heads tall, facing three-quarters right, light from the top-left):
head 9-27, neck 27-29, torso 30-54, legs 55-86, boots 86-92. The shard is always drawn
last at shard_kit.SHARD_X/SHARD_Y, so every digit sits in the same place.
"""
from __future__ import annotations

from shard_kit import Canvas, SHARD, SHARD_X, SHARD_Y, DIGIT_FONT, draw_shard, stamp

CX = 16  # body centre line


# ── shared parts ──────────────────────────────────────────────────────────────
def head(cv: Canvas, skin: str = "skin", cx: int = CX, cy: int = 18) -> None:
    cv.ellipse(cx + 0.5, cy, 7.5, 9, skin)
    cv.rect(cx - 2, cy + 8, cx + 2, cy + 11, skin)                 # neck


def eyes(cv: Canvas, colour: str, cx: int = CX, y: int = 19, look: int = 1) -> None:
    """Two 2x2 eyes with a white catch-light; ``look`` shifts the gaze (-1 left, 1 right)."""
    for ex in (cx - 4, cx + 2):
        cv.dot(ex + look, y, colour)
        cv.dot(ex + 1 + look, y, colour)
        cv.dot(ex + look, y + 1, colour)
        cv.dot(ex + 1 + look, y + 1, "outline")
        cv.dot(ex + 1 + look, y, "white")


def mouth(cv: Canvas, kind: str = "calm", cx: int = CX, y: int = 24) -> None:
    if kind == "calm":
        cv.dot(cx, y, "skin_shade")
        cv.dot(cx + 1, y, "skin_shade")
    elif kind == "smirk":
        cv.dot(cx, y, "skin_shade")
        cv.dot(cx + 1, y, "skin_shade")
        cv.dot(cx + 2, y - 1, "skin_shade")
    elif kind == "smile":
        cv.dot(cx - 1, y - 1, "crimson")
        for x in range(cx, cx + 3):
            cv.dot(x, y, "crimson")
        cv.dot(cx + 3, y - 1, "crimson")
    elif kind == "grin":
        for x in range(cx - 1, cx + 4):
            cv.dot(x, y, "white")
            cv.dot(x, y + 1, "crimson")
    elif kind == "open":
        cv.dot(cx, y, "crimson")
        cv.dot(cx + 1, y, "crimson")
        cv.dot(cx, y + 1, "crimson")
        cv.dot(cx + 1, y + 1, "crimson")


def torso(cv: Canvas, mat: str, cx: int = CX, top: int = 30, bottom: int = 54) -> None:
    cv.poly([(cx - 8, top), (cx + 9, top), (cx + 7, bottom), (cx - 6, bottom)], mat)


def legs(cv: Canvas, mat: str, boots: str, cx: int = CX, top: int = 55, bottom: int = 92) -> None:
    cv.rect(cx - 6, top, cx - 1, bottom - 6, mat)
    cv.rect(cx + 1, top, cx + 6, bottom - 6, mat)
    cv.rect(cx - 7, bottom - 6, cx - 1, bottom, boots)
    cv.rect(cx + 1, bottom - 6, cx + 7, bottom, boots)


def arm(cv: Canvas, x0: int, y0: int, x1: int, y1: int, sleeve: str, hand: str = "skin") -> None:
    cv.line(x0, y0, x1, y1, sleeve, width=3)
    cv.ellipse(x1, y1, 1.6, 1.6, hand)


def raised_hand(cv: Canvas, sleeve: str, hand: str = "skin") -> None:
    """Right arm up to the shard's base: the hand that presents it."""
    arm(cv, CX + 8, 33, 30, 31, sleeve, hand)
    cv.ellipse(32, 30, 2.2, 1.6, hand)


# ── 0 · The Nightmare Spell ──────────────────────────────────────────────────
def spell() -> Canvas:
    cv = Canvas()
    # The rune plate, floating.
    cv.rect(18, 40, 40, 60, "spell_plate")
    for y in range(45, 58, 6):                                   # engraved rune lines
        for x in range(21, 37, 3):
            if (x + y) % 2 == 0:
                cv.dot(x, y, "violet_deep")
                cv.dot(x + 1, y, "violet_deep")
    cv.dot(29, 54, "violet")
    cv.dot(28, 54, "violet")
    # Brackets reaching up around the empty socket.
    cv.rect(22, 4, 23, 30, "spell_plate")
    cv.rect(22, 4, 25, 5, "spell_plate")
    cv.rect(22, 29, 25, 30, "spell_plate")
    cv.rect(44, 4, 45, 30, "spell_plate")
    cv.rect(42, 4, 45, 5, "spell_plate")
    cv.rect(42, 29, 45, 30, "spell_plate")
    cv.rect(22, 30, 23, 40, "spell_plate")
    cv.rect(44, 30, 45, 40, "spell_plate")
    # Three threads rising from the plate (a quiet Weaver allusion).
    for x, top in ((15, 18), (18, 10), (20, 24)):
        for y in range(top, 40):
            cv.dot(x, y, "violet_deep")
    # A faint glow where it hovers.
    for x in range(22, 36):
        cv.dot(x, 72, "violet_deep")
    for x in range(25, 33):
        cv.dot(x, 73, "violet_deep")
    draw_ghost_shard(cv, "0")
    return cv


def draw_ghost_shard(cv: Canvas, digit: str) -> None:
    """The Spell's shard is an empty socket: hollow, with a violet numeral."""
    legend = {"#": ("flat", "violet"), "W": ("flat", "white"), "P": ("flat", "ink"),
              "V": ("flat", "violet_deep"), "D": ("flat", "violet_deep")}
    stamp(cv, SHARD_X, SHARD_Y, SHARD, legend)
    for dy, row in enumerate(DIGIT_FONT[digit]):
        for dx, ch in enumerate(row):
            if ch == "#":
                cv.dot(SHARD_X + 3 + dx, SHARD_Y + 7 + dy, "violet")


# ── 1 · Sunny ────────────────────────────────────────────────────────────────
def sunny() -> Canvas:
    cv = Canvas()
    # His shadow rising behind him to hold the shard: a tendril from the floor.
    # It is his own silhouette, a step behind him, with its arm raised.
    cv.ellipse(37.5, 41, 5.5, 6.5, "shadow")                      # head
    cv.poly([(30, 48), (45, 48), (43, 72), (32, 72)], "shadow")  # body
    cv.rect(32, 72, 36, 92, "shadow")
    cv.rect(39, 72, 43, 92, "shadow")
    cv.line(33, 50, 33, 31, "shadow", width=4)                   # the raised arm
    cv.ellipse(34, 29, 5, 2.5, "shadow")                         # its open palm under the shard
    legs(cv, "onyx", "onyx")
    torso(cv, "onyx")
    head(cv, "skin")
    # Messy black fringe.
    cv.poly([(8, 16), (9, 9), (13, 6), (19, 5), (24, 8), (25, 15), (22, 12), (17, 13), (12, 12), (10, 18)], "black_hair")
    for x, y in ((11, 5), (15, 4), (20, 4), (24, 6), (9, 8)):
        cv.px(x, y, "black_hair")
    cv.rect(8, 12, 9, 22, "black_hair")
    eyes(cv, "ink", look=-1)                                     # side-eye: "nothing to do with me"
    for x, y in ((11, 17), (12, 17), (18, 16), (19, 17)):         # flat, unimpressed brows
        cv.dot(x, y, "ink")
    mouth(cv, "smirk")
    # Arms crossed over the chest.
    cv.rect(8, 38, 25, 43, "onyx")
    cv.ellipse(23, 40, 2, 2, "skin")
    cv.ellipse(10, 42, 2, 2, "skin")
    # Weaver's Mask at his hip: a demon face.
    cv.ellipse(6, 52, 3, 4, "steel")
    for x, y, c in ((5, 51, "ruby"), (7, 51, "ruby"), (6, 54, "outline"), (5, 55, "outline"), (7, 55, "outline")):
        cv.dot(x, y, c)
    cv.rect(8, 50, 9, 52, "leather")
    draw_shard(cv, "1")
    return cv


# ── 2 · Nephis ───────────────────────────────────────────────────────────────
def nephis() -> Canvas:
    cv = Canvas()
    # Sword at her side, her left hand on the hilt.
    cv.rect(5, 54, 6, 84, "steel")
    cv.rect(3, 52, 8, 53, "bronze")
    legs(cv, "white_cloth", "steel")
    torso(cv, "white_cloth")
    cv.rect(CX - 6, 52, CX + 7, 54, "steel")                    # belt
    cv.rect(CX - 8, 30, CX - 4, 34, "steel")                    # pauldrons
    cv.rect(CX + 5, 30, CX + 9, 34, "steel")
    arm(cv, CX - 7, 34, 7, 52, "white_cloth")
    raised_hand(cv, "white_cloth")
    head(cv, "skin")
    # Silver hair, chin length, swept; the Crown of Dawn as a thin silver line.
    cv.poly([(8, 22), (8, 12), (11, 8), (17, 6), (23, 8), (25, 13), (25, 24), (23, 18), (21, 12), (14, 12), (10, 16)], "silver_hair")
    cv.rect(9, 9, 24, 9, "steel")
    eyes(cv, "stone", look=1)
    mouth(cv, "calm")
    # White flame wreathing the shard's base.
    for (x, y) in ((28, 27), (29, 25), (40, 27), (41, 25), (27, 22), (42, 22), (30, 29), (39, 29), (35, 30)):
        cv.ellipse(x, y, 1.6, 2.4, "flame")
    draw_shard(cv, "2")
    return cv


# ── 3 · Cassie ───────────────────────────────────────────────────────────────
def cassie() -> Canvas:
    cv = Canvas()
    # Long pale-gold hair behind her shoulders.
    cv.poly([(7, 14), (26, 14), (26, 58), (22, 62), (10, 62), (6, 58)], "gold_hair")
    # A long blue dress.
    cv.poly([(CX - 8, 30), (CX + 9, 30), (CX + 11, 90), (CX - 10, 90)], "blue_cloth")
    cv.rect(CX - 5, 90, CX - 1, 92, "leather")
    cv.rect(CX + 2, 90, CX + 6, 92, "leather")
    cv.rect(CX - 7, 46, CX + 8, 47, "gold_hair")                 # sash
    arm(cv, CX - 7, 33, 8, 54, "blue_cloth")
    # Right hand raised to her temple: she speaks into your mind.
    arm(cv, CX + 8, 33, 25, 20, "blue_cloth")
    head(cv, "skin")
    cv.poly([(8, 18), (9, 10), (14, 7), (20, 7), (24, 10), (25, 18), (22, 13), (11, 13)], "gold_hair")
    cv.rect(8, 18, 25, 20, "blue_cloth")                          # blindfold
    cv.px(9, 21, "blue_cloth")                                    # its tail
    cv.px(8, 22, "blue_cloth")
    mouth(cv, "calm")
    # The number, spoken: Spell-style brackets either side of the shard.
    for y in range(9, 26):
        cv.dot(24, y, "blue")
        cv.dot(44, y, "blue")
    for x in (25, 26, 42, 43):
        cv.dot(x, 9, "blue")
        cv.dot(x, 25, "blue")
    draw_shard(cv, "3")
    return cv


# ── 4 · Effie ────────────────────────────────────────────────────────────────
def effie() -> Canvas:
    cv = Canvas()
    # Spear: the shard is spitted on its tip.
    cv.rect(33, 27, 34, 92, "wood")
    legs(cv, "steel", "leather")
    torso(cv, "steel")
    cv.rect(CX - 6, 52, CX + 7, 54, "leather")
    arm(cv, CX + 8, 33, 32, 50, "tan", "tan")                     # gripping the spear
    cv.ellipse(33, 50, 2.2, 2, "tan")
    # Round shield on her left arm.
    cv.ellipse(7, 46, 7, 8, "bronze")
    cv.ellipse(7, 46, 3, 3.5, "steel")
    head(cv, "tan")
    # Brown hair, high ponytail; open steel helm with a tall white plume.
    cv.poly([(8, 16), (9, 9), (14, 6), (20, 6), (24, 9), (25, 16), (22, 11), (11, 11)], "brown_hair")
    cv.rect(23, 10, 26, 26, "brown_hair")
    cv.rect(9, 7, 24, 9, "steel")
    cv.rect(15, 2, 17, 6, "white_cloth")
    cv.rect(17, 1, 20, 3, "white_cloth")
    eyes(cv, "leather", look=1)
    mouth(cv, "grin")
    draw_shard(cv, "4")
    return cv


# ── 5 · Kai ──────────────────────────────────────────────────────────────────
def kai() -> Canvas:
    cv = Canvas()
    lift = -5  # he hovers: the whole figure sits 5 px higher than the others
    sub = Canvas()
    legs(sub, "ivory", "bronze", bottom=86)
    torso(sub, "ivory")
    sub.rect(CX - 6, 52, CX + 7, 53, "bronze")
    sub.rect(CX - 1, 31, CX + 1, 50, "bronze")                     # trim
    arm(sub, CX - 7, 33, 6, 50, "ivory")
    head(sub, "skin")
    sub.poly([(8, 20), (8, 11), (12, 7), (19, 6), (24, 9), (26, 16), (25, 22), (22, 13), (12, 12), (10, 20)], "auburn")
    eyes(sub, "green", look=1)
    mouth(sub, "open")
    for y in range(sub.h):
        for x in range(sub.w):
            if sub.mat[y][x] is not None and 0 <= y + lift < cv.h:
                cv.mat[y + lift][x] = sub.mat[y][x]
                cv.flat[y + lift][x] = sub.flat[y][x]
    # Bow in his left hand.
    for y in range(32, 66):
        offset = int(3 * (1 - ((y - 49) / 17) ** 2))
        cv.px(4 - offset, y, "wood")
    for y in range(33, 66):
        cv.dot(4, y, "pale")
    raised_hand(cv, "ivory")
    # He sings: one note.
    for x, y in ((26, 13), (26, 14), (26, 15), (26, 16), (26, 17), (27, 13), (28, 13), (25, 17), (25, 18), (26, 18)):
        cv.dot(x, y, "green")
    # His shadow on the ground, apart from his feet.
    for x in range(10, 24):
        cv.dot(x, 91, "ink")
    for x in range(12, 22):
        cv.dot(x, 92, "ink")
    draw_shard(cv, "5")
    return cv


# ── 6 · Jet ──────────────────────────────────────────────────────────────────
def jet() -> Canvas:
    cv = Canvas()
    # The mist scythe: a long shaft, the blade hooking over the shard.
    cv.rect(44, 4, 45, 92, "black_leather")
    cv.poly([(45, 3), (40, 1), (32, 2), (27, 5), (34, 4), (41, 5), (45, 7)], "mist")
    legs(cv, "black_leather", "black_leather")
    torso(cv, "black_leather")
    cv.rect(CX - 6, 52, CX + 7, 53, "stone")
    arm(cv, CX + 8, 33, 42, 46, "black_leather")                  # leaning on the shaft
    arm(cv, CX - 7, 33, 9, 52, "black_leather")
    head(cv, "skin")
    # Short raven-black bob.
    cv.poly([(7, 25), (7, 12), (11, 7), (18, 6), (24, 8), (26, 14), (26, 25), (23, 25), (23, 13), (11, 13), (10, 25)], "black_hair")
    eyes(cv, "blue", look=1)                                      # eyeing the shard
    cv.dot(18, 17, "ink")
    cv.dot(19, 16, "ink")
    mouth(cv, "open")
    # Soul mist around her boots.
    for x, y in ((6, 90), (9, 88), (26, 90), (23, 87), (4, 87), (28, 86)):
        cv.ellipse(x, y, 2.5, 1.5, "mist")
    draw_shard(cv, "6")
    return cv


# ── 7 · Rain ─────────────────────────────────────────────────────────────────
def rain() -> Canvas:
    cv = Canvas()
    legs(cv, "leather", "leather")
    torso(cv, "green_cloth")
    cv.rect(CX - 6, 52, CX + 7, 54, "leather")
    cv.line(CX - 7, 31, CX + 7, 52, "leather")                    # quiver strap
    cv.rect(4, 28, 7, 44, "leather")                              # quiver
    for x in (4, 6):
        cv.dot(x, 26, "pale")
        cv.dot(x, 27, "pale")
    # Bow lowered in her left hand.
    for y in range(46, 82):
        offset = int(3 * (1 - ((y - 64) / 18) ** 2))
        cv.px(6 - offset, y, "wood")
    arm(cv, CX - 7, 34, 7, 62, "green_cloth")
    raised_hand(cv, "green_cloth")                                # she has just caught it
    head(cv, "skin")
    cv.poly([(8, 18), (8, 10), (13, 6), (20, 6), (24, 9), (25, 17), (22, 12), (11, 12)], "brown_hair")
    cv.rect(23, 11, 27, 13, "brown_hair")                         # ponytail
    cv.rect(26, 13, 27, 22, "brown_hair")
    eyes(cv, "green_dark", look=1)
    mouth(cv, "smile")
    # A tiny shadow behind her heel, giving a thumbs-up.
    cv.ellipse(27, 89, 3, 3, "shadow")
    cv.dot(26, 88, "violet")
    cv.dot(28, 88, "violet")
    cv.px(31, 86, "shadow")
    cv.px(31, 85, "shadow")
    draw_shard(cv, "7")
    return cv


# ── 8 · Saint ────────────────────────────────────────────────────────────────
def saint() -> Canvas:
    cv = Canvas()
    # The round shield held high; the shard rests on it.
    cv.ellipse(34, 18, 11, 13, "stone")
    cv.ellipse(34, 18, 9, 11, "dark_armour")
    # Black blade planted beside her.
    cv.rect(4, 46, 5, 92, "onyx")
    cv.rect(2, 44, 7, 45, "dark_armour")
    # Kneeling knight: torso lower, front knee up, back knee on the ground.
    cv.poly([(CX - 8, 46), (CX + 9, 46), (CX + 7, 67), (CX - 6, 67)], "dark_armour")
    cv.rect(CX - 6, 66, CX + 12, 73, "stone")                     # front thigh, level
    cv.rect(CX + 7, 73, CX + 12, 89, "dark_armour")               # front shin
    cv.rect(CX + 7, 89, CX + 15, 92, "onyx")                      # front foot
    cv.poly([(CX - 6, 70), (CX + 1, 70), (CX, 87), (CX - 7, 87)], "dark_armour")   # back thigh
    cv.rect(CX - 10, 87, CX + 1, 92, "stone")                     # back knee and shin on the ground
    arm(cv, CX + 8, 48, 28, 30, "dark_armour", "stone")           # holding the shield up
    arm(cv, CX - 7, 48, 7, 60, "dark_armour", "stone")
    # Helm: closed, two ruby eyes behind the visor.
    cv.ellipse(CX + 0.5, 36, 7.5, 9, "dark_armour")
    cv.rect(CX - 5, 34, CX + 6, 35, "onyx")
    for x in (CX - 3, CX - 2, CX + 3, CX + 4):
        cv.dot(x, 34, "ruby")
    cv.rect(CX - 1, 24, CX + 1, 27, "stone")                       # crest
    draw_shard(cv, "8")
    return cv


# ── 9 · Mordret ──────────────────────────────────────────────────────────────
def mordret() -> Canvas:
    cv = Canvas()
    # The hand mirror: the shard exists only in its reflection.
    cv.ellipse(34.5, 16.5, 10, 14, "steel")
    cv.ellipse(34.5, 16.5, 8, 12, "mirror")
    cv.rect(33, 31, 35, 38, "steel")                               # handle
    legs(cv, "onyx", "onyx")
    torso(cv, "onyx")
    cv.rect(CX - 8, 30, CX - 7, 54, "steel")                       # silver lining of the coat
    cv.rect(CX + 8, 30, CX + 9, 52, "steel")
    arm(cv, CX + 8, 33, 33, 39, "onyx")
    arm(cv, CX - 7, 34, 6, 48, "onyx")
    cv.ellipse(5, 49, 2.5, 1.6, "skin")                            # the real hand: empty, open
    head(cv, "skin")
    cv.poly([(8, 16), (9, 9), (14, 6), (20, 6), (24, 9), (25, 15), (22, 11), (12, 11)], "black_hair")
    eyes(cv, "ink", look=0)
    mouth(cv, "smile")                                             # a pleasant smile, held too long
    draw_shard(cv, "9")
    # A hairline crack across the glass.
    for x, y in ((40, 6), (41, 5), (42, 4)):
        cv.dot(x, y, "outline")
    return cv


CAST = {
    "0": ("The Nightmare Spell", spell),
    "1": ("Sunny", sunny),
    "2": ("Nephis", nephis),
    "3": ("Cassie", cassie),
    "4": ("Effie", effie),
    "5": ("Kai", kai),
    "6": ("Jet", jet),
    "7": ("Rain", rain),
    "8": ("Saint", saint),
    "9": ("Mordret", mordret),
}
