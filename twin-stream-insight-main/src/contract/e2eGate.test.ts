/**
 * FE-11 grep gate: the E2E specs run against a REAL backend. Nothing in e2e/** may fulfil, mock or stub a request.
 * The only permitted interception is `page.routeWebSocket` (dropping/restoring the socket to test the UI's reaction).
 */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob('../../e2e/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('e2e/** is real-backend only', () => {
  it('scans the e2e specs and helpers', () => {
    expect(Object.keys(files).length).toBeGreaterThanOrEqual(4);
  });

  it.each([
    ['page.route / context.route (request interception)', /\.\s*route\s*\(/],
    ['route.fulfill / route.continue / route.abort', /\.\s*(fulfill|abort)\s*\(|route\.continue\s*\(/],
    ['HAR replay', /routeFromHAR/],
    ['mock server libraries', /\b(msw|nock|mockttp|json-server|wiremock)\b/i],
    ['a fake WebSocket class', /class\s+\w*(Fake|Mock)\w*\s+extends/i],
    ['Math.random', /Math\.random/],
  ])('no %s', (_label, re) => {
    const offenders = Object.entries(files)
      .filter(([, src]) => re.test(strip(src)))
      .map(([p]) => p);
    expect(offenders).toEqual([]);
  });

  it('every spec signs in through the real login helper or screen', () => {
    for (const [path, src] of Object.entries(files)) {
      if (!/\.spec\.ts$/.test(path)) continue;
      expect(/signIn\(|Sign in to TwinGrid/.test(src), path).toBe(true);
    }
  });
});
