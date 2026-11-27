# Soul-Shard Counter — Design

A live visitor counter for the top of this repository's README. Each digit is a *Shadow Slave*
character presenting a **soul shard** carved with that digit: every README view is one more soul.

Approved 2026-11-27. Scope: **this repository only** (one counter, not a public service).

## 1. Decisions

| Topic | Decision |
| --- | --- |
| Purpose | Live visitor count of this README (GitHub fetches the image through Camo on every view). |
| Concept | Visitors are soul shards. Every character holds **the same shard sprite**, digit carved in the same pixel font at the same spot; personality lives in the pose. |
| Lineup | 0 Spell · 1 Sunny · 2 Nephis · 3 Cassie · 4 Effie · 5 Kai · 6 Jet · 7 Rain · 8 Saint · 9 Mordret |
| Style | Pixel art, heroic proportions, **48 × 96 px** per digit, shown at exactly 2× with `image-rendering: pixelated`. |
| Palette | One shared 24-colour palette (§4). 1 px `#111827` outline + light rim pixels so sprites read on `#0d1117` and `#ffffff`. |
| Art method | Paper-doll pixel kit: shared skeletons + layered parts + hand-placed detail, authored as code/text, compiled to PNG. Any sprite may later be replaced by a hand-drawn PNG of the same size. |
| Hosting | Cloudflare Workers + D1 (free tier). |
| Display | 7 digits, zero-padded: leading zeros are the Spell's empty sockets. Caption below in the same pixel font: `[ 4,182 souls have heard this story ]`. |

## 2. The cast

All poses keep the shard's centre inside the **shard zone** (x 24–44, y 6–40) so the numbers line up.

| # | Character | Pose | Lore anchor (novel, vol 8–11) |
| :-: | --- | --- | --- |
| 0 | **The Nightmare Spell** | No body: a floating rune plate, an **empty socket `[ 0 ]`**, three threads above, rune ticks below. | Bracketed Spell messages; "the Nightmare Spell whispered" |
| 1 | **Sunny** | Arms crossed, side-eye; **his shadow rises behind him and holds the shard up**. Weaver's Mask (demon face) at his hip. | onyx armour; Weaver's Mask "the ferocious face of a demon" |
| 2 | **Nephis** | Composed; the shard rests on her open palm wreathed in **white flame**; other hand on her sword. | silver hair, grey eyes, white clothes; "a ball of white flame dancing on her palm" |
| 3 | **Cassie** | Blindfolded, fingertips at her temple; the shard glows there and a pixel **`[ 3 ]`** bracket floats beside her: the number spoken into your mind. | blind seer; "Cassie's voice resounded in his head" |
| 4 | **Effie** | The huntress: polished steel, white plume, round shield raised, **shard spitted on her spear tip** like a trophy, easy grin. | spear and shield; "polished steel… a tall white plume" |
| 5 | **Kai** | **Hovering** above his own shadow, auburn hair, bow; holds the shard up to the light; two note pixels: he sings. | "remarkable green eyes", "auburn hair", "ivory armour", "beautiful voice" |
| 6 | **Jet** | Leans on her **mist scythe**, shard hooked on the blade, **eyeing it hungrily**; soul mist at her boots. | "raven-black hair", "icy blue eyes", scythe / mist blade; sustained by soul essence |
| 7 | **Rain** | Bow just lowered, **catches the shard** in one hand; a tiny shadow behind her heel gives a thumbs-up. | archer; "her teacher" (Sunny, hidden) |
| 8 | **Saint** | **Kneels, presenting the shard on her round shield**; ruby eyes behind the visor. | "graceful stone knight", "two ruby flames… behind the visor", "black blade and a round shield" |
| 9 | **Mordret** | Holds a hand mirror; **the shard exists only in the reflection**, his real hand empty. | mirrors and reflections; "pleasant smile", "infinite coldness" |

## 3. Components

```
counter/
  DESIGN.md
  art/                      Python (repo's toolchain), offline build step
    shard_palette.py        the 24 colours, single source of truth
    shard_kit.py            canvas, drawing primitives, skeletons, parts, shard, pixel font
    shard_cast.py           the ten characters assembled from the kit
    build.py                validate → PNG (sprites/) → preview sheets → worker/src/sprites.generated.ts
    sprites/0.png … 9.png   48×96 RGBA, palette-only
    preview/                lineup on dark, light, transparent; 1× and 2×; critique rounds
  worker/                   TypeScript Cloudflare Worker
    src/index.ts            routing, counting, headers
    src/render.ts           SVG compositor (pure function)
    src/sprites.generated.ts  written by art/build.py — never edited by hand
    test/                   vitest
    wrangler.toml, schema.sql, package.json
```

### 3.1 Contract: `sprites.generated.ts`

```ts
export const SPRITE_W = 48;
export const SPRITE_H = 96;
/** Base64 PNGs (no data: prefix), keys "0".."9". */
export const DIGITS: Record<string, string>;
/** Pixel font for the caption: glyph rows of '#' (ink) and '.' (blank). */
export const FONT: { width: number; height: number; glyphs: Record<string, string[]> };
```
`FONT` covers `0-9 , [ ] space` and the lowercase letters of the caption. Unknown characters render as blank.

### 3.2 Worker behaviour

- `GET /@:name` — increments `name`, returns the SVG. `name` must match `^[a-z0-9-]{1,40}$` and be in the
  allow-list `COUNTERS` (default `one-who-reads-aloud`); anything else renders without counting.
- `GET /@:name?num=N` — renders N without counting (previews).
- `GET /health` — `ok`.
- Query: `digits` (1–10, default 7), `scale` (1–4, default 2), `bg` (`transparent` default, `dark`, `light`),
  `caption` (`1` default, `0` hides it).
- Storage: D1 table `counters(name TEXT PRIMARY KEY, count INTEGER NOT NULL)`; increment is one atomic
  `INSERT … ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`.
- Rate cap: at most 10 increments per name per second (counter in memory per isolate, plus D1's atomic
  update); requests over the cap render the current count without incrementing. Requests come from
  GitHub's Camo, so there is no per-visitor de-duplication.
- Headers: `Content-Type: image/svg+xml; charset=utf-8`,
  `Cache-Control: max-age=0, no-cache, no-store, must-revalidate`, `Pragma: no-cache`, `Expires: 0`,
  `X-Content-Type-Options: nosniff`.
- Errors never return HTML: on a storage failure it renders the last known count (or `num`) with no caption.

### 3.3 Compositor

- One `<image>` per distinct digit in `<defs>`, `<use>` per position; integer coordinates only.
- Digit width 48 × scale, no gap; caption centred below, each font pixel drawn as `scale`-sized `<rect>`s
  merged into one `<path>` per caption; caption colour `#8b949e` (readable on both GitHub themes).
- Root `<svg>` carries `shape-rendering="crispEdges"` and `style="image-rendering:pixelated"`.
- Payload budget: < 25 KB for 7 digits with caption.

## 4. Palette

`#111827` outline · `#222b3b` black hair/shadow · `#3a4658` dark armour · `#66758a` stone/steel shade ·
`#aab7c7` steel/mirror · `#e5edf5` pale/silver · `#ffffff` flame core/glint · `#f2d2bc` skin ·
`#d9a88e` skin shade · `#ad7866` tanned skin · `#704f49` dark leather · `#725047` brown/leather ·
`#9c4a2f` auburn · `#b98a52` bronze · `#f1d38a` pale gold · `#6e243a` deep crimson · `#e34b62` ruby ·
`#bda6ff` spell violet (shard, Sunny's shadow rim) · `#5b4ba8` deep violet · `#246b57` dark green ·
`#60c99a` green · `#155e8a` deep blue · `#54cae8` blue · `#b8f2f2` icy cyan

## 5. Quality gates

1. `art/build.py` refuses: wrong size, off-palette pixel, shard missing from the shard zone, an opaque
   pixel on the sprite edge without an outline neighbour.
2. Two critique rounds on rendered PNGs (dark + light, 1× + 2×): silhouette recognition, legibility of a
   random 7-digit number, cohesion, lore.
3. Worker: vitest for routing, validation, counting, rate cap, headers, SVG structure and size budget.
4. Python: pytest for palette validation and the generated TypeScript module.

## 6. Legal

Unofficial, non-commercial fan art. *Shadow Slave* © Guiltythree. Code MIT; sprites CC BY-NC 4.0.
