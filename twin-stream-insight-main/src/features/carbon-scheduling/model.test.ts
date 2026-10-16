import { describe, expect, it } from "vitest";
import { MAX_DURATION_H, MAX_LOAD_KW, formatIntensity, formatKg, hourLabel, parseDuration, parseLoadKw, savingWording, showsWindow, stripDescription, windowHours, windowLabel } from "./model";
import { varying } from "./testData";

describe("parseDuration", () => {
  it("accepts whole hours 1..24 and nothing else (never clamps)", () => {
    expect(parseDuration("1")).toEqual({ ok: true, value: 1 });
    expect(parseDuration(" 4 ")).toEqual({ ok: true, value: 4 });
    expect(parseDuration(String(MAX_DURATION_H))).toEqual({ ok: true, value: 24 });
    for (const bad of ["", "0", "-1", "2.5", "abc", "1e1", "25", "٣"]) expect(parseDuration(bad).ok).toBe(false);
  });
});

describe("parseLoadKw", () => {
  it("accepts (0, max] and rejects everything else", () => {
    expect(parseLoadKw("100")).toEqual({ ok: true, value: 100 });
    expect(parseLoadKw("0.5")).toEqual({ ok: true, value: 0.5 });
    expect(parseLoadKw(String(MAX_LOAD_KW))).toEqual({ ok: true, value: MAX_LOAD_KW });
    for (const bad of ["", "0", "-3", "abc", "Infinity", "NaN", String(MAX_LOAD_KW + 1)]) expect(parseLoadKw(bad).ok).toBe(false);
  });
});

describe("formatting", () => {
  it("formats hours, windows, emissions and intensity", () => {
    expect(hourLabel(5)).toBe("05:00");
    expect(windowLabel(22, 2)).toBe("22:00 to 02:00");
    expect(formatKg(120.64)).toBe("120.6 kg CO₂");
    expect(formatIntensity(301.5)).toBe("302 gCO₂/kWh");
  });
  it("a window wraps past midnight", () => {
    expect([...windowHours(22, 4)].sort((a, b) => a - b)).toEqual([0, 1, 22, 23]);
    expect(windowHours(0, 24).size).toBe(24);
  });
});

describe("saving wording", () => {
  it("words a saving against the right baseline, and zero as the same", () => {
    const s = varying().savings!;
    expect(savingWording(s, "average_of_allowed_windows")).toEqual({ kind: "saves", text: "Saves 4.0 kg CO₂ (3.2 %) vs the average start time." });
    expect(savingWording(s, "reference_start").text).toBe("Saves 4.0 kg CO₂ (3.2 %) vs your reference start time.");
    expect(savingWording({ emissions_kg: 0, pct: 0 }, "reference_start")).toEqual({ kind: "same", text: "Same emissions as your reference start time." });
    expect(savingWording({ emissions_kg: 2, pct: null }, "average_of_allowed_windows").text).toBe("Saves 2.0 kg CO₂ vs the average start time.");
  });
});

describe("what may show a window", () => {
  it("only the data-backed and the labelled synthetic statuses", () => {
    expect(showsWindow("ok")).toBe(true);
    expect(showsWindow("synthetic_demo")).toBe(true);
    expect(showsWindow("no_variation")).toBe(false);
    expect(showsWindow("unverified")).toBe(false);
  });
});

describe("strip description", () => {
  it("names the lowest and highest hour and the best window", () => {
    const curve = varying().curve_gco2_per_kwh!;
    expect(stripDescription(curve, { start_hour: 0, end_hour: 4 })).toBe(
      "Carbon intensity by site-local hour: lowest 300 gCO₂/kWh at 00:00, highest 323 gCO₂/kWh at 23:00. Best window 00:00 to 04:00, outlined.",
    );
    expect(stripDescription(curve, null)).not.toContain("Best window");
  });
});
