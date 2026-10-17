import { describe, expect, it } from "vitest";
import {
  EMPTY_FORM,
  MAX_ASSIGNEE,
  MAX_DESCRIPTION,
  MAX_TITLE,
  formFromAlert,
  formFromHealth,
  latestText,
  needsAttention,
  originText,
  parseCreate,
  trendText,
  worstSensor,
} from "./model";
import { plant, sensor } from "./testFixtures";

const form = (over: object = {}) => ({ ...EMPTY_FORM, ...over });

describe("parseCreate", () => {
  it("a manual order needs a title; nothing optional is sent when empty", () => {
    expect(parseCreate(form())).toEqual({ ok: false, errors: { title: "Enter a title." } });
    expect(parseCreate(form({ title: "  Replace filter  " }))).toEqual({
      ok: true,
      body: { title: "Replace filter", priority: "medium", source: { kind: "manual" } },
    });
  });

  it("sends description, assignee and priority when given, trimmed", () => {
    const r = parseCreate(form({ title: "t", description: " d ", assignee: " sam ", priority: "high" }));
    expect(r).toEqual({ ok: true, body: { title: "t", description: "d", assignee: "sam", priority: "high", source: { kind: "manual" } } });
  });

  it("an alert order needs a chosen alert and sends its id as a number; the title is optional", () => {
    expect(parseCreate(form({ sourceKind: "alert" }))).toEqual({ ok: false, errors: { alertId: "Choose an alert." } });
    for (const bad of ["0", "-3", "abc", "1.5", ""]) expect(parseCreate(form({ sourceKind: "alert", alertId: bad })).ok).toBe(false);
    expect(parseCreate(form({ sourceKind: "alert", alertId: "12" }))).toEqual({
      ok: true,
      body: { priority: "medium", source: { kind: "alert", alert_id: 12 } },
    });
  });

  it("a health order needs an asset, and sends the sensor only when one is chosen", () => {
    expect(parseCreate(form({ sourceKind: "health" }))).toEqual({ ok: false, errors: { assetExternalId: "Choose an asset." } });
    expect(parseCreate(form({ sourceKind: "health", assetExternalId: "facility-level" }))).toEqual({
      ok: true,
      body: { priority: "medium", asset_external_id: "facility-level", source: { kind: "health" } },
    });
    expect(parseCreate(form({ sourceKind: "health", assetExternalId: "facility-level", measurand: "it_power_kw" }))).toMatchObject({
      ok: true,
      body: { source: { kind: "health", measurand: "it_power_kw" } },
    });
  });

  it("never sends an asset for a manual order, even if one was left in the form", () => {
    const r = parseCreate(form({ title: "t", assetExternalId: "facility-level" }));
    expect(r.ok && "asset_external_id" in r.body).toBe(false);
  });

  it("names too-long fields instead of cutting them", () => {
    const r = parseCreate(form({ title: "x".repeat(MAX_TITLE + 1), description: "y".repeat(MAX_DESCRIPTION + 1), assignee: "z".repeat(MAX_ASSIGNEE + 1) }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(Object.keys(r.errors).sort()).toEqual(["assignee", "description", "title"]);
    expect(parseCreate(form({ title: "x".repeat(MAX_TITLE) })).ok).toBe(true);
  });
});

describe("prefill", () => {
  it("from a health row: the asset, its worst sensor, and a priority from the status", () => {
    const calm = sensor({ measurand: "humidity_pct", external_id: "fac1.humidity_pct", status: "watch" });
    const asset = plant({ sensors: [calm, sensor()], status: "warning" });
    expect(worstSensor(asset)?.measurand).toBe("it_power_kw");
    expect(formFromHealth(asset)).toMatchObject({ sourceKind: "health", assetExternalId: "facility-level", measurand: "it_power_kw", priority: "high" });
    expect(formFromHealth(plant({ status: "watch", sensors: [calm] }))).toMatchObject({ priority: "medium", measurand: "humidity_pct" });
  });

  it("an asset whose sensors have no data has no worst sensor", () => {
    expect(worstSensor(plant({ sensors: [sensor({ status: "no_data" })] }))).toBeNull();
    expect(formFromHealth(plant({ sensors: [] })).measurand).toBe("");
  });

  it("from an alert: the alert id only", () => {
    expect(formFromAlert(5)).toMatchObject({ sourceKind: "alert", alertId: "5", title: "" });
  });
});

describe("wording", () => {
  it("only watch and warning rows offer a work order", () => {
    expect(["ok", "watch", "warning", "no_data"].map((s) => needsAttention(s as never))).toEqual([false, true, true, false]);
  });

  it("describes a trend in words, and says so when there is none", () => {
    expect(trendText(sensor())).toBe("Trend: up 39.0 kW over 3.3 h (39% of the valid range).");
    expect(trendText(sensor({ trend: { slope_per_day: 0, change_over_window: 0, span_hours: 5, drift_pct_of_range: 0, direction: "flat" } }))).toBe("Trend: flat over 5.0 h.");
    expect(trendText(sensor({ trend: null }))).toBe("Trend: not enough valid samples (NOT MEASURED).");
    expect(trendText(sensor({ trend: { slope_per_day: -1, change_over_window: -2, span_hours: 1, drift_pct_of_range: null, direction: "down" } }))).toBe("Trend: down 2.0 kW over 1.0 h.");
  });

  it("never prints a number for a missing value", () => {
    expect(latestText(sensor())).toBe("49.0 kW");
    expect(latestText(sensor({ latest: null }))).toBe("no valid value");
  });

  it("says whether an order came from simulated data or was typed", () => {
    expect(originText({ origin: "manual", source_kind: "manual" })).toBe("entered by hand");
    expect(originText({ origin: "simulated", source_kind: "alert" })).toBe("from simulated alert");
    expect(originText({ origin: "simulated", source_kind: "health" })).toBe("from simulated health data");
  });
});
