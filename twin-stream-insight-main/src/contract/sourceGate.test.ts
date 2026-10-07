/** Static gates over the contract layer's own source (FE-01: "a schema may not default a missing value"). */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = Object.entries(files).filter(([path]) => !/\.test\.ts$/.test(path));

const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('contract layer source gates', () => {
  it('scans real source files', () => {
    expect(sources.length).toBeGreaterThan(8);
  });
  it.each([
    ['.default(', /\.default\s*\(/],
    ['.catch(', /\.catch\s*\(/], // zod .catch() would silently replace a bad value
    ['.coerce', /z\.coerce\b/],
    ['Math.random', /Math\.random/],
  ])('no %s in contract source', (_label, re) => {
    const offenders = sources.filter(([, src]) => re.test(stripComments(src))).map(([p]) => p);
    expect(offenders).toEqual([]);
  });
});
