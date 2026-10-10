/** FE-15 static gates: no hardcoded scenario list, no synthetic data, no real-facility-control wording. */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob(['./**/*.{ts,tsx}', '../components/scenario/Scenario{Library,Picker,ParamForm}.tsx', '../components/scenario/CustomParameters.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const sources = Object.entries(files).filter(([p]) => !/\.test\.tsx?$/.test(p) && !/testFixtures\.ts$/.test(p));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('scenario source gates', () => {
  it('scans real files', () => expect(sources.length).toBeGreaterThanOrEqual(9));

  it('no scenario id is hardcoded (ids come from the backend registry)', () => {
    expect(sources.filter(([, s]) => /['"`]whatif-[\w-]*['"`]/.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it.each([
    ['Math.random', /Math\.random/],
    ['Date.now / new Date()', /Date\.now\s*\(|new Date\(\s*\)/],
    ['performance.now', /performance\.now/],
  ])('no %s', (_n, re) => {
    expect(sources.filter(([, s]) => re.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('no real-facility-control wording in user-visible strings', () => {
    const strings = sources.flatMap(([p, s]) => (strip(s).match(/(['"`])(?:(?!\1)[^\\\n]|\\.)*\1|>[^<>{}\n]+</g) ?? []).map((t) => `${p}: ${t}`));
    expect(strings.filter((t) => /\b(apply|applied|deploy|deployed|actuate|execute)\b/i.test(t))).toEqual([]);
  });

  it('the weather label is never derived from the scenario label or id', () => {
    const model = strip(files['./model.ts']);
    const body = model.slice(model.indexOf('export function weatherPlantText'), model.indexOf('export function controlText'));
    expect(body.length).toBeGreaterThan(100);
    expect(body).not.toMatch(/\.label\b|\.id\b|\.description\b/);
  });
});
