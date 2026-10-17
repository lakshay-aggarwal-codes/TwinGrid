/** FE-16 static gates: no fake progress, no client timers/clocks, no hardcoded scenario ids, no real-facility-control wording. */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob(['./**/*.{ts,tsx}', '../components/runs/Run{Start,Monitor,StatusPanel,ResultPanel}.tsx', '../pages/Runs.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const sources = Object.entries(files).filter(([p]) => !/\.test\.tsx?$/.test(p) && !/testFixtures\.ts$/.test(p));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('run source gates', () => {
  it('scans real files', () => expect(sources.length).toBeGreaterThanOrEqual(10));

  it.each([
    ['Math.random', /Math\.random/],
    ['Date.now / new Date()', /Date\.now\s*\(|new Date\(\s*\)/],
    ['performance.now', /performance\.now/],
    ['own timers (React Query owns the polling schedule)', /\bsetInterval\b|\bsetTimeout\b/],
    ['a progress bar', /role=["']progressbar["']|<Progress\b|progressbar/i],
    ['an ETA / percent-complete', /\bETA\b|percent complete|% complete/i],
  ])('no %s', (_n, re) => {
    expect(sources.filter(([, s]) => re.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('no scenario id is hardcoded', () => {
    expect(sources.filter(([, s]) => /['"`]whatif-[\w-]*['"`]/.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('no real-facility-control wording in user-visible strings', () => {
    const strings = sources.flatMap(([p, s]) => (strip(s).match(/(['"`])(?:(?!\1)[^\\\n]|\\.)*\1|>[^<>{}\n]+</g) ?? []).map((t) => `${p}: ${t}`));
    expect(strings.filter((t) => /\b(apply|applied|deploy|deployed|actuate|execute|dispatch)\b/i.test(t))).toEqual([]);
  });

  it('no verdict wording on results', () => {
    expect(sources.filter(([, s]) => /\bwinner\b|\bbetter\b|\brecommend|\boptimi[sz]ed\b|\bAI-/i.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('the status switch has no default that treats an unknown status as a known one', () => {
    const model = strip(files['./model.ts']);
    const body = model.slice(model.indexOf('function viewOf'), model.indexOf('export function describeStatus'));
    expect(body).toMatch(/assertNever\(status\)/);
  });
});
