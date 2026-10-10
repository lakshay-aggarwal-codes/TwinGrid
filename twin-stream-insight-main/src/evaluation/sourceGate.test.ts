/** FE-17 static gates: the evaluation surface renders backend data; it must not rank, score, sort, or imply superiority. */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob(['./**/*.{ts,tsx}', '../components/evaluation/*.tsx', '../pages/Evaluation.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const sources = Object.entries(files).filter(([p]) => !/\.test\.tsx?$/.test(p) && !/testFixtures\.ts$/.test(p));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('evaluation source gates', () => {
  it('scans real files', () => expect(sources.length).toBeGreaterThanOrEqual(10));

  it.each([
    ['sorting', /\.sort\s*\(|\.toSorted\s*\(/],
    ['ranking / best-of / min-max selection', /\.reduce\s*\(|Math\.(min|max)\s*\(|\brank(ing|ed)?\b/i],
    ['winner / best-row highlighting', /\bwinner\b|isBest|bestRow|highlight/i],
    ['"optimized" claims', /\boptimi[sz]ed\b/i],
    ['Math.random', /Math\.random/],
    ['Date.now / new Date()', /Date\.now\s*\(|new Date\(\s*\)/],
    ['client carbon / PUE maths', /\*\s*475|475\s*\*|\*\s*0\.4\b|\*\s*1\.35/],
  ])('no %s', (_n, re) => {
    expect(sources.filter(([, s]) => re.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('no real-facility-control wording in user-visible strings', () => {
    const strings = sources.flatMap(([p, s]) => (strip(s).match(/(['"`])(?:(?!\1)[^\\\n]|\\.)*\1|>[^<>{}\n]+</g) ?? []).map((t) => `${p}: ${t}`));
    expect(strings.filter((t) => /\b(apply|applied|deploy|deployed|actuate|execute|recommend(ed)?|savings?)\b/i.test(t))).toEqual([]);
  });

  it('never imports a raw feed Frame type', () => {
    expect(sources.filter(([, s]) => /\bFrame\b/.test(strip(s))).map(([p]) => p)).toEqual([]);
  });
});
