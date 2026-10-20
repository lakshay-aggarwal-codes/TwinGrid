import { describe, expect, it } from "vitest";
import { LAB_BOUNDS, defaultInputs, normalise, setpointRangeOf, snapSetpoint, toParams } from "./model";
import { parseLabUrl, withLabParams } from "./url";

/** SYNTHETIC `setpoint_check` payloads in the shape `GET /api/optimizer/baseline-recommendation` sends (`rules.setpoint_check`). */
const check = (physics: string, range: unknown) => ({
  setpoint_check: { physics_version: physics, actuator_range_C: range, proposed_within_actuator_range: true, reference_within_actuator_range: true },
});

const LEGACY_0 = setpointRangeOf(check("0", [5, 15]));
const PHYSICS_1 = setpointRangeOf(check("1", [16, 25]));

/** Physics 2 is a valid twin version but the RL environment (which owns the actuator range) refuses it, so the backend sends no range for it: nothing to assert beyond "unavailable". */
describe("the set-point range comes from the server's setpoint_check", () => {
  it("reads legacy-0 as 5 to 15 and physics 1 as 16 to 25, with the physics it was given for", () => {
    expect(LEGACY_0).toEqual({ min: 5, max: 15, step: 0.5, unit: "°C", physics: "0" });
    expect(PHYSICS_1).toEqual({ min: 16, max: 25, step: 0.5, unit: "°C", physics: "1" });
  });

  it("is null, never a guessed range, for anything unusable", () => {
    for (const bad of [null, undefined, {}, { setpoint_check: 5 }, { setpoint_check: [] }, check("1", [16]), check("1", ["a", "b"]), check("1", [20, 20]), check("1", [25, 16]), check("1", [16, Number.NaN])]) {
      expect(setpointRangeOf(bad as object | null | undefined)).toBeNull();
    }
  });

  it("no longer has a fixed set-point bound among the lab's constants", () => {
    expect(Object.keys(LAB_BOUNDS)).toEqual(["itLoadPct", "ambientC"]);
  });
});

describe.each([
  ["legacy-0", LEGACY_0, 5, 15, 7],
  ["physics 1", PHYSICS_1, 16, 25, 16],
])("%s", (_name, range, lo, hi, def) => {
  it("takes its bounds and default from the range", () => {
    if (range === null) throw new Error("fixture range is null");
    expect([range.min, range.max]).toEqual([lo, hi]);
    expect(defaultInputs(range).setpointC).toBe(def);
    expect(toParams(defaultInputs(range)).chilled_water_temp).toBe(def);
  });

  it("validates by snapping into the range and falling back on NaN", () => {
    if (range === null) throw new Error("fixture range is null");
    expect(snapSetpoint(lo - 3, range, def)).toBe(lo);
    expect(snapSetpoint(hi + 3, range, def)).toBe(hi);
    expect(snapSetpoint(lo + 0.74, range, def)).toBe(lo + 0.5);
    expect(snapSetpoint(Number.NaN, range, def)).toBe(def);
    expect(normalise({ setpointC: 1000 }, range).setpointC).toBe(hi);
    expect(normalise({}, range).setpointC).toBe(def);
  });

  it("round-trips through the address, omitting the default and snapping a linked value", () => {
    if (range === null) throw new Error("fixture range is null");
    const d = defaultInputs(range);
    expect(withLabParams("", { scenario: d, baseline: d }, range)).toBe("");
    const moved = { ...d, setpointC: hi };
    const search = withLabParams("", { scenario: moved, baseline: d }, range);
    expect(parseLabUrl(search, range)).toEqual({ scenario: moved, baseline: d });
    expect(parseLabUrl("?set=0", range).scenario.setpointC).toBe(lo);
    expect(parseLabUrl("?set=99", range).scenario.setpointC).toBe(hi);
  });
});

describe("the legacy 5 to 15 values do not leak into physics 1", () => {
  it("the physics-1 default, bounds and snapping never produce a value below 16", () => {
    if (PHYSICS_1 === null) throw new Error("fixture range is null");
    expect(defaultInputs(PHYSICS_1).setpointC).toBeGreaterThanOrEqual(16);
    expect(snapSetpoint(7, PHYSICS_1, 16)).toBe(16);
    expect(snapSetpoint(15, PHYSICS_1, 16)).toBe(16);
    expect(parseLabUrl("?set=7&bset=15", PHYSICS_1).scenario.setpointC).toBe(16);
    expect(parseLabUrl("?bset=15", PHYSICS_1).baseline.setpointC).toBe(16);
  });
});
