// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { renderCounter } from '../src/render';
import type { RenderOptions } from '../src/render';
import { DIGITS, FONT, SPRITE_H, SPRITE_W } from '../src/sprites.generated';

function render(overrides: Partial<RenderOptions> = {}): string {
  return renderCounter({ count: 0, digits: 7, scale: 2, bg: 'transparent', caption: true, ...overrides });
}

function displayedDigits(svg: string): string {
  return [...svg.matchAll(/<use href="#digit-(\d)"/g)].map((match) => match[1]).join('');
}

describe('renderCounter', () => {
  it('pads with zeroes, preserves long counts, and clamps negatives', () => {
    expect(displayedDigits(render())).toBe('0000000');
    expect(displayedDigits(render({ count: 42 }))).toBe('0000042');
    expect(displayedDigits(render({ count: 123456789, digits: 2 }))).toBe('123456789');
    expect(displayedDigits(render({ count: -10 }))).toBe('0000000');
  });

  it('defines each distinct digit once and references it per position', () => {
    const svg = render({ count: 1212121 });
    expect(svg.match(/<image /g)).toHaveLength(2);
    expect(svg.match(/<use /g)).toHaveLength(7);
    const defs = svg.match(/<defs>(.*?)<\/defs>/)?.[1] ?? '';
    expect(defs.match(/id="digit-1"/g)).toHaveLength(1);
    expect(defs.match(/id="digit-2"/g)).toHaveLength(1);
    expect(defs).toContain('href="data:image/png;base64,');
  });

  it.each([
    [0, '[ 0 souls have heard this story ]'],
    [1, '[ 1 soul has heard this story ]'],
    [2, '[ 2 souls have heard this story ]'],
    [4182, '[ 4,182 souls have heard this story ]'],
    [1e12, '[ 1,000,000,000,000 souls have heard this story ]'],
  ] as const)('formats the caption for %s', (count, caption) => {
    const svg = render({ count });
    expect(svg).toContain(`<path fill="#8b949e" aria-label="${caption}"`);
    expect(svg.match(/<path /g)).toHaveLength(1);
    expect(svg).not.toContain('<text');
  });

  it('omits the caption and its space when hidden, retaining accessibility', () => {
    const svg = render({ count: 1, caption: false });
    expect(svg).not.toContain('<path');
    expect(svg).toContain('height="192" viewBox="0 0 672 192"');
    expect(svg).toContain('role="img" aria-label="1 soul has heard this story"');
    expect(svg).toContain('<title>1 soul has heard this story</title>');
  });

  it.each(['transparent', 'dark', 'light'] as const)('renders the %s background', (bg) => {
    const svg = render({ bg });
    if (bg === 'transparent') {
      expect(svg).not.toContain('<rect');
    } else {
      expect(svg.match(/<rect /g)).toHaveLength(1);
      expect(svg).toContain(`fill="${bg === 'dark' ? '#0d1117' : '#ffffff'}"`);
    }
  });

  it.each([1, 2, 3, 4])('uses integer coordinates and scale-sized caption squares at scale %s', (scale) => {
    const svg = render({ count: 4182, scale });
    for (const match of svg.matchAll(/(?:x|y|width|height|viewBox)="([^"]+)"/g)) {
      expect(match[1]).toMatch(/^\d+(?: \d+)*$/);
    }
    const path = svg.match(/ d="([^"]+)"/)?.[1] ?? '';
    const squares = [...path.matchAll(/M(\d+) (\d+)h(\d+)v(\d+)h-(\d+)z/g)];
    expect(squares.length).toBeGreaterThan(0);
    expect(squares.map((match) => match[0]).join('')).toBe(path);
    for (const square of squares) {
      expect(square.slice(3)).toEqual([String(scale), String(scale), String(scale)]);
    }
    expect(Math.min(...squares.map((square) => Number(square[2])))).toBe((SPRITE_H + 4) * scale);
    const caption = '[ 4,182 souls have heard this story ]';
    const captionWidth = (caption.length * (FONT.width + 1) - 1) * scale;
    // The first ink pixel sits wherever the font's '[' glyph starts, relative to the caption origin.
    const firstInk = Math.min(...(FONT.glyphs['['] ?? ['#']).map((row) => (row.indexOf('#') + 1 || Infinity) - 1));
    expect(Number(squares[0]?.[1])).toBe(Math.floor((7 * SPRITE_W * scale - captionWidth) / 2) + firstInk * scale);
    expect(svg).toContain('shape-rendering="crispEdges" style="image-rendering:pixelated"');
  });

  it('fits a caption even when the digit row is shorter', () => {
    const svg = render({ count: 1, digits: 1, scale: 1 });
    const width = ('[ 1 soul has heard this story ]'.length * (FONT.width + 1) - 1);
    expect(svg).toContain(`viewBox="0 0 ${width} 107"`);
    expect(svg).toContain(`<use href="#digit-1" x="${Math.floor((width - SPRITE_W) / 2)}" y="0"/>`);
  });

  it('stays below 25 KB with seven distinct placeholder digits and caption', () => {
    expect(new TextEncoder().encode(render({ count: 1234567, scale: 4 })).byteLength).toBeLessThan(25_000);
  });

  it('supplies the generated asset contract and complete caption font', () => {
    expect([SPRITE_W, SPRITE_H, FONT.width, FONT.height]).toEqual([48, 96, 5, 7]);
    expect(Object.keys(DIGITS).sort().join('')).toBe('0123456789');
    for (const character of new Set('0123456789,[] souls have heard this story')) {
      expect(FONT.glyphs[character]).toHaveLength(7);
      for (const row of FONT.glyphs[character] ?? []) expect(row).toMatch(/^[#.]{5}$/);
    }
  });
});
