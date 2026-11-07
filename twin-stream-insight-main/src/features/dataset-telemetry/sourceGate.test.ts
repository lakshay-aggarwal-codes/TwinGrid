/** Static gates: the dataset readout must not reach the live feed, facility topology, the shared provenance badge or stream=live. */
import { describe, expect, it } from "vitest";

const files = import.meta.glob("./*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const sources = Object.entries(files).filter(([p]) => !/\.test\.tsx?$/.test(p) && !p.endsWith("fixtures.ts"));
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");

describe("dataset-telemetry source gates", () => {
  it("scans the feature's own source", () => expect(sources.length).toBeGreaterThanOrEqual(6));
  it.each([
    ["live feed", /@\/telemetry\/useFeed|useFeed\b/],
    ["facility topology / 3D scene", /@\/three\/|useTopology|findRack/],
    ["shared provenance module", /@\/provenance/],
    ["stream=live", /stream\s*[=:]\s*["']?live\b/],
    ["zod default/catch/coerce", /\.default\s*\(|\.catch\s*\(|z\.coerce\b/],
    ["Math.random", /Math\.random/],
    ["fabricated placeholder numbers", /toFixed\s*\(/],
  ])("no %s", (_n, re) => {
    for (const [path, src] of sources) expect(strip(src), path).not.toMatch(re);
  });
});
