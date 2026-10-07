/** FE-05 static gates over the provenance source ("no code path yields `measured` without backend origin `measured`"). */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = Object.entries(files).filter(([path]) => !/\.test\.tsx?$/.test(path));
const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('provenance source gates', () => {
  it('scans the real source files', () => {
    expect(sources.length).toBeGreaterThanOrEqual(8);
  });

  it("the `'measured'` literal is interpreted in exactly one place (classifyOrigin's case)", () => {
    const hits = sources.flatMap(([path, src]) =>
      stripComments(src)
        .split('\n')
        .filter((line) => /['"`]measured['"`]/.test(line))
        .map((line) => `${path}: ${line.trim()}`),
    );
    const interpreting = hits.filter((h) => /case 'measured':/.test(h));
    expect(interpreting).toHaveLength(1);
    expect(interpreting[0]).toMatch(/^\.\/model\.ts:/);
    // The only other mentions are type/vocabulary declarations and the OriginState union.
    for (const h of hits.filter((x) => !/case 'measured':/.test(x))) {
      expect(h).toMatch(/OriginState|state: 'measured'|origin: 'measured'/);
    }
  });

  it('nothing builds a measured origin from a default or a fallback', () => {
    for (const [path, src] of sources) {
      const code = stripComments(src);
      expect(code, path).not.toMatch(/origin\s*(\?\?|\|\|)\s*['"]measured['"]/);
      expect(code, path).not.toMatch(/origin\s*=\s*['"]measured['"]/);
    }
  });

  it.each([
    ['Math.random', /Math\.random/],
    ['Date.now / new Date() (browser clock is never data time)', /Date\.now\s*\(|new Date\(\s*\)/],
    ['performance.now', /performance\.now/],
  ])('no %s in provenance source', (_label, re) => {
    const offenders = sources.filter(([, src]) => re.test(stripComments(src))).map(([p]) => p);
    expect(offenders).toEqual([]);
  });

  it('components take a ProvenanceView, never a bare string label', () => {
    for (const [path, src] of sources.filter(([p]) => /\/(ProvenanceBadge|ProvenanceStrip|ProvenanceDetail|FreshnessChip)\.tsx$/.test(p))) {
      expect(src, path).toMatch(/view: ProvenanceView/);
      expect(src, path).not.toMatch(/\b(origin|label|provenance)\??: string\b/);
    }
  });
});
