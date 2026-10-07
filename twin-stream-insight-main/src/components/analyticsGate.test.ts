/**
 * FE-08 static gates over the analytics surface: no fabricated figures, no client clock, FloorHeatmap gone.
 * (Comments are stripped before matching, so explanatory comments may name what was removed.)
 */
import { describe, expect, it } from "vitest";

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
const raw = (m: Record<string, unknown>) =>
  Object.entries(m)
    .filter(([p]) => !/\.test\.tsx?$/.test(p))
    .map(([p, src]) => [p, strip(src as string)] as const);

// `ui/` is vendored shadcn code (not edited by FE-08); everything else under src/components is app code.
const components = raw(import.meta.glob("./**/*.tsx", { query: "?raw", import: "default", eager: true })).filter(
  ([p]) => !p.startsWith("./ui/")
);
const allSrc = raw(import.meta.glob("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }));
const hook = allSrc.find(([p]) => p.endsWith("/hooks/useSimulation.ts"))![1];
const header = components.find(([p]) => p.endsWith("/DashboardHeader.tsx"))![1];

describe("FE-08 grep gate (src/components)", () => {
  it("scans real files", () => {
    expect(components.length).toBeGreaterThan(10);
  });
  it.each([
    ["1.35 (invented baseline)", /1\.35/],
    ["* 0.4 (invented carbon factor)", /\*\s*0\.4\b/],
    ["+ 40 (invented overhead)", /\+\s*40\b/],
    ["Math.random", /Math\.random/],
    ["Systems Online", /Systems Online/],
    ["Water Saved", /Water Saved/],
    ["CO₂ Avoided", /CO₂ Avoided/],
  ])("no %s", (_label, re) => {
    expect(components.filter(([, src]) => re.test(src)).map(([p]) => p)).toEqual([]);
  });
});

describe("FE-08 client derivations are gone from the hook", () => {
  it("no water/hour = wue x it_power", () => {
    expect(hook).not.toMatch(/wue\s*\*/);
    expect(hook).not.toMatch(/waterPerHour/);
  });
  it("an unrecognised cooling mode is never mapped to 'Auto'", () => {
    expect(hook).not.toMatch(/apiToCoolingMode/);
    expect(hook).not.toMatch(/\|\|\s*'Auto'/);
  });
});

describe("FE-08 header", () => {
  it("has no browser clock", () => {
    expect(header).not.toMatch(/setInterval|toLocale(Time|Date)String|new Date\(/);
  });
});

describe("FE-08 FloorHeatmap is deleted", () => {
  it("the file does not exist", () => {
    expect(allSrc.map(([p]) => p).filter((p) => /FloorHeatmap/.test(p))).toEqual([]);
  });
  it("nothing imports it (import graph empty)", () => {
    expect(allSrc.filter(([, src]) => /FloorHeatmap/.test(src)).map(([p]) => p)).toEqual([]);
  });
});
