import { describe, expect, it } from "vitest";
import { CB, CB_SERIES, LINE_COLORS, MODE_COLORS, contrastRatio } from "./chartPalette";

const DARK_CARD = "#141414";
const LIGHT_CARD = "#FFFFFF";
const PATTERN_INK = "#020617"; // the dark mark SimulationTab draws over a mode colour

describe("colour-blind-safe chart palette", () => {
  it("is the eight Okabe-Ito colours, all different", () => {
    expect(new Set(Object.values(CB)).size).toBe(8);
    expect(CB_SERIES).toHaveLength(8);
    expect(new Set(CB_SERIES).size).toBe(8);
  });

  it("cooling modes get five different colours", () => {
    expect(new Set(Object.values(MODE_COLORS)).size).toBe(5);
  });

  it("line colours keep at least 3:1 against both the dark and the light card", () => {
    for (const c of LINE_COLORS) {
      expect(contrastRatio(c, DARK_CARD)).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(c, LIGHT_CARD)).toBeGreaterThanOrEqual(3);
    }
  });

  it("the dark pattern marks stay readable over every mode colour", () => {
    for (const c of Object.values(MODE_COLORS)) expect(contrastRatio(c, PATTERN_INK)).toBeGreaterThanOrEqual(4.5);
  });

  it("contrastRatio is symmetric and 21:1 for black on white", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 5);
  });
});
