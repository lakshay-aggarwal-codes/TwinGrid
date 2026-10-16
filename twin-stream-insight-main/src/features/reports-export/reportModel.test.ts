import { describe, expect, it } from "vitest";
import type { LiveStatePayload } from "@/api/models";
import { buildPrintableReport, carbonLabelFor, CLAIM_BOUNDARY, NOT_REPORTED } from "./reportModel";

const frame = (over: Partial<LiveStatePayload> = {}): LiveStatePayload => ({
  timestamp: "2026-01-01T00:05:00", server_utilisation: 0.5, outside_temp_C: 20, server_inlet_temp_C: 24, server_outlet_temp_C: 35,
  it_power_kw: 100, cooling_power_kw: 25, total_power_kw: 125, pue: 1.25, water_flow_lpm: 60, water_consumed_L: 1234.4, wue: 0.456,
  humidity_pct: 40, water_pressure_bar: 2, cooling_mode: "chiller", anomaly: 0,
  carbon_intensity_gco2_per_kwh: 475, carbon_gco2: 59375, carbon_data_is_real: false,
  origin: "simulated", seq: 7, ts_ingest: "2026-10-16T03:15:00+00:00", sim_time: "2026-01-01T00:05:00",
  ...over,
});
const at = new Date(Date.UTC(2026, 9, 16, 3, 20, 0));
const build = (f: LiveStatePayload | null, state: "live" | "stale" = "live") => buildPrintableReport({ frame: f, feed: { state, ageMs: 12000 }, generatedAt: at });

describe("buildPrintableReport", () => {
  it("copies values from the frame with their units and source fields", () => {
    const r = build(frame());
    const row = (item: string) => r.rows.find((x) => x.item === item)!;
    expect(row("PUE")).toMatchObject({ value: "1.25", source: "pue" });
    expect(row("WUE")).toMatchObject({ value: "0.456", unit: "L/kWh" });
    expect(row("Water consumed")).toMatchObject({ value: "1234", unit: "L" });
    expect(r.hasData).toBe(true);
  });
  it("labels the carbon fallback as an assumption, on the label and on the rows", () => {
    const r = build(frame());
    expect(r.carbonLabel).toMatch(/ASSUMPTION/);
    expect(r.carbonLabel).toMatch(/475 gCO₂\/kWh/);
    expect(r.carbonLabel).toMatch(/not real grid data/);
    expect(r.rows.some((x) => x.section === "Carbon" && /assumed fallback/.test(x.item))).toBe(true);
    expect(r.rows.some((x) => /modelled from the assumed intensity/.test(x.item))).toBe(true);
  });
  it("does not call a loaded series live and does not mention the fallback", () => {
    const r = build(frame({ carbon_data_is_real: true, carbon_intensity_gco2_per_kwh: 310 }));
    expect(r.carbonLabel).toMatch(/not a live grid feed/);
    expect(r.carbonLabel).not.toMatch(/ASSUMPTION/);
  });
  it("says so when carbon is not reported", () => {
    expect(carbonLabelFor(null)).toMatch(/not reported/);
    const r = build(frame({ carbon_data_is_real: undefined }));
    expect(r.rows.some((x) => x.section === "Carbon")).toBe(false);
    expect(r.carbonLabel).toMatch(/no carbon figure is stated/);
  });
  it("always carries the claim boundary: simulated, not measured, not calibrated, not an audited disclosure", () => {
    const text = build(frame()).claimBoundary.join(" ");
    expect(build(null).claimBoundary).toBe(CLAIM_BOUNDARY);
    expect(text).toMatch(/simulation-based digital twin/);
    expect(text).toMatch(/not measured/);
    expect(text).toMatch(/no calibration/);
    expect(text).toMatch(/not an audited/);
  });
  it("prints a provenance footer with origin, the Simulated data label and UTC times", () => {
    const f = Object.fromEntries(build(frame()).provenanceFooter.map((x) => [x.label, x.value]));
    expect(f["Data origin"]).toBe("simulated");
    expect(f["Labelled"]).toBe("Simulated data");
    expect(f["Server ingest time (UTC)"]).toBe("2026-10-16T03:15:00.000Z");
    expect(f["Frame time (simulated clock)"]).toBe("2026-01-01T00:05:00");
    expect(f["Generated (UTC, browser clock)"]).toBe("2026-10-16T03:20:00.000Z");
    expect(f["Feed state at generation"]).toBe("live");
  });
  it("states gaps instead of filling them", () => {
    const f = Object.fromEntries(build(frame({ origin: undefined, seq: undefined, ts_ingest: undefined })).provenanceFooter.map((x) => [x.label, x.value]));
    expect(f["Data origin"]).toBe(NOT_REPORTED);
    expect(f["Frame sequence"]).toBe(NOT_REPORTED);
    expect(f["Server ingest time (UTC)"]).toBe(NOT_REPORTED);
  });
  it("warns when the feed was stale, and when there was no frame", () => {
    expect(build(frame(), "stale").banners[0]).toMatch(/^STALE: .*12 s/);
    expect(build(frame(), "live").banners).toEqual([]);
    const none = build(null);
    expect(none.hasData).toBe(false);
    expect(none.rows).toEqual([]);
    expect(none.banners[0]).toMatch(/no live frame/i);
  });
});
