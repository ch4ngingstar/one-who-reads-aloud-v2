import { DIGITS, FONT, SPRITE_H, SPRITE_W } from './sprites.generated';

export interface RenderOptions {
  count: number;
  digits: number;
  scale: number;
  bg: 'transparent' | 'dark' | 'light';
  caption: boolean;
}

export function renderCounter(opts: RenderOptions): string {
  const count = Number.isFinite(opts.count) ? Math.max(0, Math.trunc(opts.count)) : 0;
  const scale = Number.isFinite(opts.scale) ? Math.max(1, Math.min(4, Math.trunc(opts.scale))) : 2;
  const digits = Number.isFinite(opts.digits) ? Math.max(1, Math.min(10, Math.trunc(opts.digits))) : 7;
  const formatted = count.toLocaleString('en-US', { maximumFractionDigits: 0 });
  const label = count === 1 ? '1 soul has heard this story' : `${formatted} souls have heard this story`;
  const caption = `[ ${label} ]`;
  const sequence = formatted.replaceAll(',', '').padStart(digits, '0');
  const digitWidth = SPRITE_W * scale;
  const digitHeight = SPRITE_H * scale;
  const rowWidth = sequence.length * digitWidth;
  const captionWidth = opts.caption ? (caption.length * (FONT.width + 1) - 1) * scale : 0;
  // Short counters still need enough canvas to avoid clipping the caption.
  const width = Math.max(rowWidth, captionWidth);
  const height = digitHeight + (opts.caption ? (4 + FONT.height) * scale : 0);
  const rowX = Math.floor((width - rowWidth) / 2);
  const defs = [...new Set(sequence)].map((digit) =>
    `<image id="digit-${digit}" width="${digitWidth}" height="${digitHeight}" href="data:image/png;base64,${DIGITS[digit]}"/>`,
  ).join('');
  const uses = [...sequence].map((digit, index) =>
    `<use href="#digit-${digit}" x="${rowX + index * digitWidth}" y="0"/>`,
  ).join('');
  const background = opts.bg === 'dark' ? '#0d1117' : opts.bg === 'light' ? '#ffffff' : null;
  const rect = background ? `<rect width="${width}" height="${height}" fill="${background}"/>` : '';
  const pixels: string[] = [];
  if (opts.caption) {
    const left = Math.floor((width - captionWidth) / 2);
    const top = digitHeight + 4 * scale;
    [...caption].forEach((character, index) => {
      // Missing font glyphs deliberately occupy a blank character cell.
      FONT.glyphs[character]?.forEach((row, y) => {
        [...row].forEach((pixel, x) => {
          if (pixel === '#') {
            const px = left + (index * (FONT.width + 1) + x) * scale;
            pixels.push(`M${px} ${top + y * scale}h${scale}v${scale}h-${scale}z`);
          }
        });
      });
    });
  }
  const path = opts.caption ? `<path fill="#8b949e" aria-label="${caption}" d="${pixels.join('')}"/>` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" shape-rendering="crispEdges" style="image-rendering:pixelated" role="img" aria-label="${label}"><title>${label}</title>${rect}<defs>${defs}</defs>${uses}${path}</svg>`;
}
