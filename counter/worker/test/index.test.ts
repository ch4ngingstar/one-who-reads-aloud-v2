// @vitest-environment node
import { describe, expect, it } from 'vitest';
import worker, { handleRequest, parseOptions, RateLimiter } from '../src/index';
import type { Env } from '../src/index';

class FakeD1 {
  readonly counts = new Map<string, number>();
  readonly queries: { sql: string; values: unknown[] }[] = [];
  failure: 'prepare' | 'bind' | 'first' | null = null;

  prepare(sql: string) {
    if (this.failure === 'prepare') throw new Error('Storage unavailable');
    return {
      bind: (...values: unknown[]) => {
        if (this.failure === 'bind') throw new Error('Binding failed');
        const execute = () => {
          if (this.failure === 'first') throw new Error('Query failed');
          this.queries.push({ sql, values });
          const name = String(values[0]);
          if (/^INSERT/.test(sql)) {
            const count = (this.counts.get(name) ?? 0) + 1;
            this.counts.set(name, count);
            return { count };
          }
          if (/^SELECT/.test(sql)) {
            const count = this.counts.get(name);
            return count === undefined ? null : { count };
          }
          throw new Error(`Unexpected SQL: ${sql}`);
        };
        return {
          first: async () => execute(),
          run: async () => {
            const row = execute();
            return { success: true, results: row ? [row] : [], meta: {} };
          },
        };
      },
    };
  }
}

const NAME = 'one-who-reads-aloud';

function fixture(counters?: string) {
  const db = new FakeD1();
  // Only the D1 methods used by the handler need an implementation in Node.
  const env: Env = { DB: db as unknown as D1Database };
  if (counters !== undefined) env.COUNTERS = counters;
  let time = 100;
  const limiter = new RateLimiter(() => time);
  return {
    db,
    env,
    advance: (milliseconds: number) => { time += milliseconds; },
    request: (path = `/@${NAME}`, method = 'GET') =>
      handleRequest(new Request(`https://example.test${path}`, { method }), env, limiter),
  };
}

describe('parseOptions', () => {
  it('uses the specified defaults', () => {
    expect(parseOptions(new URLSearchParams())).toEqual({
      digits: 7, scale: 2, bg: 'transparent', caption: true, num: null,
    });
  });

  it('clamps integers and recognizes presentation options', () => {
    expect(parseOptions(new URLSearchParams('digits=99&scale=-3&bg=dark&caption=0&num=4182'))).toEqual({
      digits: 10, scale: 1, bg: 'dark', caption: false, num: 4182,
    });
    expect(parseOptions(new URLSearchParams('digits=0&scale=99&bg=light'))).toMatchObject({
      digits: 1, scale: 4, bg: 'light',
    });
  });

  it('falls back for malformed values', () => {
    expect(parseOptions(new URLSearchParams('digits=2.5&scale=2px&bg=red&caption=no'))).toMatchObject({
      digits: 7, scale: 2, bg: 'transparent', caption: true,
    });
  });

  it.each(['', '-1', '1.5', 'abc', 'Infinity', '1e3', '1000000000001'])('makes invalid num=%s a zero preview', (num) => {
    expect(parseOptions(new URLSearchParams({ num })).num).toBe(0);
  });

  it.each(['0', '1', '1000000000000'])('accepts preview integer %s', (num) => {
    expect(parseOptions(new URLSearchParams({ num })).num).toBe(Number(num));
  });
});

describe('Worker', () => {
  it('increments atomically and returns SVG with exactly the required headers', async () => {
    const { request, db } = fixture();
    const response = await request();
    expect(response.status).toBe(200);
    expect(Object.fromEntries(response.headers.entries())).toEqual({
      'content-type': 'image/svg+xml; charset=utf-8',
      'cache-control': 'max-age=0, no-cache, no-store, must-revalidate',
      pragma: 'no-cache', expires: '0', 'x-content-type-options': 'nosniff',
    });
    expect(await response.text()).toContain('<title>1 soul has heard this story</title>');
    expect(db.counts.get(NAME)).toBe(1);
    expect(db.queries).toHaveLength(1);
    expect(db.queries[0]?.sql).toMatch(/ON CONFLICT\(name\) DO UPDATE SET count = counters.count \+ 1 RETURNING count/);
    expect(db.queries[0]?.values).toEqual([NAME]);
    expect(await (await request()).text()).toContain('<title>2 souls');
  });

  it('accepts a trimmed comma-separated allow-list', async () => {
    const { request, db } = fixture(' alpha, beta ');
    await request('/@alpha');
    await request('/@beta');
    await request();
    expect([...db.counts.entries()]).toEqual([['alpha', 1], ['beta', 1]]);
  });

  it.each(['unknown', '', 'Upper', 'has_underscore', 'a/b', 'a'.repeat(41), '%61lpha'])('renders unapproved or invalid name %s without touching storage', async (name) => {
    const { request, db } = fixture(`${NAME},${name}`);
    const path = name === 'unknown' ? '/@unlisted' : `/@${name}`;
    const response = await request(path);
    expect(response.headers.get('content-type')).toBe('image/svg+xml; charset=utf-8');
    expect(await response.text()).toContain('<title>0 souls');
    expect(db.queries).toHaveLength(0);
  });

  it('treats an explicitly empty allow-list as disabled', async () => {
    const { request, db } = fixture('');
    await request();
    expect(db.queries).toHaveLength(0);
  });

  it.each(['0', '4182', '1000000000000', '-1', 'broken', ''])('never counts previews with num=%s', async (num) => {
    const { request, db } = fixture();
    db.counts.set(NAME, 9);
    const response = await request(`/@${NAME}?num=${num}`);
    expect(await response.text()).toContain('<svg');
    expect(db.counts.get(NAME)).toBe(9);
    expect(db.queries).toHaveLength(0);
  });

  it('renders previews and presentation options on unknown names', async () => {
    const { request, db } = fixture();
    const svg = await (await request('/@unknown?num=42&digits=1&scale=1&bg=light&caption=0')).text();
    expect(svg).toContain('<title>42 souls');
    expect(svg).toContain('viewBox="0 0 96 96"');
    expect(svg).toContain('fill="#ffffff"');
    expect(svg).not.toContain('<path');
    expect(db.queries).toHaveLength(0);
  });

  it('reads without incrementing on non-GET counter requests', async () => {
    const { request, db } = fixture();
    db.counts.set(NAME, 7);
    expect(await (await request(`/@${NAME}`, 'POST')).text()).toContain('<title>7 souls');
    expect(db.counts.get(NAME)).toBe(7);
    expect(db.queries[0]?.sql).toBe('SELECT count FROM counters WHERE name = ?');
  });

  it('caps concurrent increments at ten, reads the 11th, and resumes after one second', async () => {
    const { request, db, advance } = fixture();
    const responses = await Promise.all(Array.from({ length: 11 }, () => request()));
    expect(db.counts.get(NAME)).toBe(10);
    expect(db.queries.filter(({ sql }) => sql.startsWith('INSERT'))).toHaveLength(10);
    expect(db.queries[10]?.sql).toBe('SELECT count FROM counters WHERE name = ?');
    expect(await responses[10]?.text()).toContain('<title>10 souls');
    advance(999);
    await request();
    expect(db.counts.get(NAME)).toBe(10);
    advance(1);
    await request();
    expect(db.counts.get(NAME)).toBe(11);
  });

  it.each(['prepare', 'bind', 'first'] as const)('returns zero SVG without caption when %s fails', async (stage) => {
    const { request, db } = fixture();
    db.failure = stage;
    const response = await request();
    const svg = await response.text();
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/svg+xml; charset=utf-8');
    expect(svg).toContain('<title>0 souls');
    expect(svg).not.toContain('<path');
    expect(svg).not.toContain('<html');
  });

  it('handles read failures and allows previews during outages', async () => {
    const { request, db } = fixture();
    db.failure = 'first';
    const read = await (await request(`/@${NAME}`, 'POST')).text();
    expect(read).toContain('<title>0 souls');
    expect(read).not.toContain('<path');
    expect(await (await request(`/@${NAME}?num=1234`)).text()).toContain('<title>1,234 souls');
  });

  it('serves health through the default export without storage', async () => {
    const { env, db } = fixture();
    db.failure = 'prepare';
    const response = await worker.fetch(new Request('https://example.test/health'), env);
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    expect(await response.text()).toBe('ok');
  });

  it.each(['/', '/other', '/health/'])('returns a plain text 404 for %s', async (path) => {
    const { request } = fixture();
    const response = await request(path);
    expect(response.status).toBe(404);
    expect(response.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    expect(await response.text()).toBe('Not found');
  });
});

describe('RateLimiter', () => {
  it('tracks names independently and expires each timestamp in a rolling window', () => {
    let time = 0;
    const limiter = new RateLimiter(() => time);
    for (let i = 0; i < 5; i++) expect(limiter.allow('a')).toBe(true);
    time = 500;
    for (let i = 0; i < 5; i++) expect(limiter.allow('a')).toBe(true);
    expect(limiter.allow('a')).toBe(false);
    expect(limiter.allow('b')).toBe(true);
    time = 1_000;
    for (let i = 0; i < 5; i++) expect(limiter.allow('a')).toBe(true);
    expect(limiter.allow('a')).toBe(false);
  });
});
