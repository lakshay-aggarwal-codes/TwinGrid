/** FE-18 static gates: the history surface renders stored backend samples; it must not resample, re-sort, interpolate or invent. */
import { describe, expect, it } from 'vitest';

const files = import.meta.glob(['./**/*.{ts,tsx}', '../../components/charts/*.tsx', '../../pages/TelemetryHistory.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const sources = Object.entries(files).filter(([p]) => !/\.test\.tsx?$/.test(p) && !/testFixtures\.ts$/.test(p));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
// The page owns the one browser-clock read (the end of the REQUESTED window). Nothing else may touch the clock.
const clockFree = sources.filter(([p]) => !/pages\/TelemetryHistory\.tsx$/.test(p));

describe('telemetry history source gates', () => {
  it('scans real files', () => expect(sources.length).toBeGreaterThanOrEqual(10));

  it.each([
    ['sorting (the backend order is authoritative)', /\.sort\s*\(|\.toSorted\s*\(/],
    ['downsampling / aggregation / smoothing', /\b(downsample|decimate|resample|aggregate)\w*\s*\(|\.reduce\s*\(|\bmovingAverage\b|\bsmooth(ing)?\b|\bbucket/i],
    ['interpolation', /interpolat|connectNulls\s*=\s*\{?\s*true|type="monotone"|type="natural"/i],
    ['Math.random', /Math\.random/],
    ['polling timers', /setInterval|refetchInterval\s*:\s*(?!false)\S/],
    ['a client stale flag', /\bstale\b/i],
    ['per-rack attribution', /\brack\b/i],
    ['"latest value" claims', /latest value|\blatest\b/i],
    ['browser storage', /localStorage|sessionStorage/],
  ])('no %s', (_n, re) => {
    expect(sources.filter(([, s]) => re.test(strip(s))).map(([p]) => p)).toEqual([]);
  });

  it('the clock is read in exactly one place (the page, for the requested window end)', () => {
    expect(clockFree.filter(([, s]) => /Date\.now\s*\(|new Date\(\s*\)|performance\.now/.test(strip(s))).map(([p]) => p)).toEqual([]);
    const page = sources.find(([p]) => /pages\/TelemetryHistory\.tsx$/.test(p));
    expect(page).toBeDefined();
    expect((strip(page![1]).match(/Date\.now\s*\(/g) ?? []).length).toBeGreaterThan(0);
  });

  it('no real-facility-control wording in user-visible strings', () => {
    const strings = sources.flatMap(([p, s]) => (strip(s).match(/(['"`])(?:(?!\1)[^\\\n]|\\.)*\1|>[^<>{}\n]+</g) ?? []).map((t) => `${p}: ${t}`));
    expect(strings.filter((t) => /\b(apply|applied|deploy|deployed|actuate|execute|recommend(ed)?|savings?|optimi[sz]ed)\b/i.test(t))).toEqual([]);
  });

  it('never imports a raw feed Frame type or the live feed (history is never filled from the WebSocket)', () => {
    expect(sources.filter(([, s]) => /\bFrame\b|useFeed|feedStore|connectWebSocket/.test(strip(s))).map(([p]) => p)).toEqual([]);
  });
});
