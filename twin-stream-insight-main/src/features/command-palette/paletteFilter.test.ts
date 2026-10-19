import { describe, expect, it } from "vitest";
import { paletteFilter } from "./items";

describe("paletteFilter (Task 15)", () => {
  const telemetryKeywords = ["history", "samples", "sensors", "gaps", "Telemetry history"];
  it("does not match a scattered subsequence (cmdk default matched 'analyt' against Telemetry history)", () => {
    expect(paletteFilter("page:/telemetry", "analyt", telemetryKeywords)).toBe(0);
  });
  it("matches a substring of a keyword or label, case-insensitively, and ranks word starts higher", () => {
    expect(paletteFilter("page:/telemetry", "HIST", telemetryKeywords)).toBeGreaterThan(0);
    expect(paletteFilter("page:/telemetry", "stor", telemetryKeywords)).toBeGreaterThan(0);
    expect(paletteFilter("x", "hist", ["history"])).toBeGreaterThan(paletteFilter("x", "stor", ["history"]));
  });
  it("requires every typed term to match", () => {
    expect(paletteFilter("x", "go analytics", ["Go to Analytics"])).toBeGreaterThan(0);
    expect(paletteFilter("x", "go zzz", ["Go to Analytics"])).toBe(0);
  });
  it("shows everything for an empty search", () => {
    expect(paletteFilter("x", "   ", [])).toBeGreaterThan(0);
  });
});
