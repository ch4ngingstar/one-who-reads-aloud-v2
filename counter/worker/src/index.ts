import { renderCounter } from './render';
import type { RenderOptions } from './render';

export interface Env {
  DB: D1Database;
  COUNTERS?: string;
}

interface Options extends Omit<RenderOptions, 'count'> {
  num: number | null;
}

function boundedInteger(value: string | null, fallback: number, min: number, max: number): number {
  if (value === null || !/^-?\d+$/.test(value)) return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(min, Math.min(max, number)) : fallback;
}

export function parseOptions(query: URLSearchParams): Options {
  const rawNum = query.get('num');
  const number = rawNum !== null && /^\d+$/.test(rawNum) ? Number(rawNum) : NaN;
  const bg = query.get('bg');
  return {
    digits: boundedInteger(query.get('digits'), 7, 1, 10),
    scale: boundedInteger(query.get('scale'), 2, 1, 4),
    bg: bg === 'dark' || bg === 'light' ? bg : 'transparent',
    caption: query.get('caption') !== '0',
    // Even malformed previews must never accidentally increment the live counter.
    num: rawNum === null ? null : Number.isInteger(number) && number <= 1e12 ? number : 0,
  };
}

export class RateLimiter {
  constructor(
    private readonly now: () => number = Date.now,
    private readonly timestamps: Map<string, number[]> = new Map(),
  ) {}

  allow(name: string): boolean {
    const now = this.now();
    const recent = (this.timestamps.get(name) ?? []).filter((time) => time > now - 1_000);
    this.timestamps.set(name, recent);
    if (recent.length >= 10) return false;
    // Reserve synchronously before awaiting D1 so concurrent requests share the cap.
    recent.push(now);
    return true;
  }
}

const incrementTimestamps = new Map<string, number[]>();
const rateLimiter = new RateLimiter(Date.now, incrementTimestamps);
const SVG_HEADERS = {
  'Content-Type': 'image/svg+xml; charset=utf-8',
  'Cache-Control': 'max-age=0, no-cache, no-store, must-revalidate',
  Pragma: 'no-cache',
  Expires: '0',
  'X-Content-Type-Options': 'nosniff',
};

export async function handleRequest(
  request: Request,
  env: Env,
  limiter: RateLimiter = rateLimiter,
): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === '/health' && request.method === 'GET') {
    return new Response('ok', { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }
  if (!url.pathname.startsWith('/@')) {
    return new Response('Not found', { status: 404, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }

  const options = parseOptions(url.searchParams);
  const name = url.pathname.slice(2);
  const allowed = new Set((env.COUNTERS ?? 'one-who-reads-aloud').split(',').map((entry) => entry.trim()));
  let count = options.num ?? 0;
  let caption = options.caption;
  try {
    if (options.num === null && /^[a-z0-9-]{1,40}$/.test(name) && allowed.has(name)) {
      const increment = request.method === 'GET' && limiter.allow(name);
      const sql = increment
        ? `INSERT INTO counters (name, count) VALUES (?, 1)
           ON CONFLICT(name) DO UPDATE SET count = counters.count + 1 RETURNING count`
        : 'SELECT count FROM counters WHERE name = ?';
      const row = await env.DB.prepare(sql).bind(name).first<{ count: number }>();
      count = row?.count ?? 0;
    }
  } catch {
    // Database outages must still produce a usable image for the README.
    count = options.num ?? 0;
    caption = false;
  }
  return new Response(renderCounter({ ...options, count, caption }), { headers: SVG_HEADERS });
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
};
