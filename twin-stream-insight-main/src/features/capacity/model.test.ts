import { describe, expect, it } from "vitest";
import { DEFAULT_PLAN, ESTIMATE_LABEL, PLAN_BOUNDS, fmt, overlayPatch, parsePlan, rows, verdictSentence } from "./model";
import { capacity, side } from "./testFixtures";

describe("parsePlan", () => {
  it("accepts whole racks and a decimal kW, trimmed", () => {
    expect(parsePlan(" 12 ", " 7.5 ")).toEqual({ ok: true, plan: { addRacks: 12, kwPerRack: 7.5 } });
    expect(parsePlan("0", "0.1")).toEqual({ ok: true, plan: { addRacks: 0, kwPerRack: 0.1 } });
    expect(parsePlan(String(PLAN_BOUNDS.maxRacks), "60")).toMatchObject({ ok: true });
  });

  it.each(["", "abc", "-1", "1.5", "201", "1e2", "0x10"])("rejects %j racks by name, without clamping", (racks) => {
    const r = parsePlan(racks, "8");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors).toEqual({ racks: "Enter a whole number from 0 to 200." });
  });

  it.each(["", "abc", "0", "0.09", "60.1", "-3", "8,5", ".5"])("rejects %j kW by name, without clamping", (kw) => {
    const r = parsePlan("5", kw);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors).toEqual({ kw: "Enter a number from 0.1 to 60 kW." });
  });

  it("names both fields when both are wrong", () => {
    const r = parsePlan("x", "y");
    expect(r.ok === false && Object.keys(r.errors).sort()).toEqual(["kw", "racks"]);
  });

  it("the default plan is itself valid", () => {
    expect(parsePlan(String(DEFAULT_PLAN.addRacks), String(DEFAULT_PLAN.kwPerRack))).toMatchObject({ ok: true });
  });
});

describe("wording", () => {
  it("states the plan, the verdict and that it is an estimate", () => {
    expect(verdictSentence(capacity())).toBe("10 more racks at 8 kW: fits with little margin (model-based estimate).");
    expect(verdictSentence(capacity({ plan: { add_racks: 1, kw_per_rack: 5, added_kw: 5 }, verdict: "does_not_fit" }))).toBe("1 more rack at 5 kW: does not fit (model-based estimate).");
    expect(verdictSentence(capacity({ plan: { add_racks: 0, kw_per_rack: 8, added_kw: 0 }, verdict: "fits" }))).toBe("Current headroom (model-based estimate): fits as is.");
    expect(ESTIMATE_LABEL).toBe("model-based estimate");
  });

  it("never prints a blank or a 0 for a value the model does not provide", () => {
    expect(fmt(null, "kW")).toBe("not modelled");
    expect(fmt(25, "kW")).toBe("25.0 kW");
    expect(fmt(-5.04, "kW")).toBe("-5.0 kW");
  });
});

describe("rows", () => {
  it("lists power, cooling, thermal and inlet with the limit only where there is one", () => {
    const r = rows(capacity());
    expect(r.map((x) => x.key)).toEqual(["power", "cooling", "thermal", "inlet"]);
    expect(r[0]).toMatchObject({ limit: 500, now: 105, withPlan: 25, nowStatus: "ok", planStatus: "tight" });
    expect(r[1]).toMatchObject({ limit: 550, now: 155, withPlan: 75 });
    expect(r[2]).toMatchObject({ limit: null, unit: "°C", now: 8.3, withPlan: 6.7 });
  });

  it("carries an unmodelled cooling limit through as null (physics without a cooling model)", () => {
    const base = side({ cooling_capacity_kw: null, cooling_headroom_kw: null, status: { power: "ok", cooling: "unknown", thermal: "ok" } });
    const r = rows(capacity({ baseline: base, with_plan: base }));
    expect(r[1]).toMatchObject({ limit: null, now: null, withPlan: null, planStatus: "unknown" });
  });
});

describe("overlayPatch", () => {
  it("is the plan's worst status and facility totals; nothing while there is no result", () => {
    expect(overlayPatch(capacity())).toEqual({ status: "tight", powerKw: 25, coolingKw: 75 });
    expect(overlayPatch(null)).toEqual({ status: null, powerKw: null, coolingKw: null });
  });
});
