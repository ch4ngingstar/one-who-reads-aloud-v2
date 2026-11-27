// Writes static SVGs through the real compositor, for the README before (or without) a deployment.
//   npm run preview   ->  docs/assets/soul-shards-cast.svg, counter/art/preview/counter-sample.svg
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderCounter } from '../src/render';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

function write(relative: string, svg: string): void {
  const path = resolve(root, relative);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, svg, 'utf8');
  console.log(`${relative}  ${svg.length} bytes`);
}

// "0123456789" is the whole cast in order; no caption, because it is not a visitor count.
write('docs/assets/soul-shards-cast.svg',
  renderCounter({ count: 123456789, digits: 10, scale: 2, bg: 'transparent', caption: false }));
// A sample of what the live counter looks like, for local review only (not a real count).
write('counter/art/preview/counter-sample.svg',
  renderCounter({ count: 4182, digits: 7, scale: 2, bg: 'dark', caption: true }));
