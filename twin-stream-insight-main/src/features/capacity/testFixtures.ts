/** Task 26 test fixture: a response shaped like the backend's (values are SYNTHETIC test numbers, not measurements). */
import type { Capacity, CapacitySide } from "./schema";

export const side = (over: Partial<CapacitySide> = {}): CapacitySide => ({
  it_power_kw: 395,
  cooling_power_kw: 127,
  pue: 1.32,
  max_outlet_temp_C: 36.7,
  power_headroom_kw: 105,
  power_limit_kw: 500,
  cooling_headroom_kw: 155,
  cooling_capacity_kw: 550,
  thermal_margin_C: 8.3,
  inlet_margin_C: 9,
  status: { power: "ok", cooling: "ok", thermal: "ok" },
  overall: "ok",
  ...over,
});

export const capacity = (over: Partial<Capacity> = {}): Capacity => ({
  label: "model-based estimate",
  origin: "simulated",
  basis: "BASIS TEXT",
  limits_note: "Power and cooling headroom are facility totals.",
  plan: { add_racks: 10, kw_per_rack: 8, added_kw: 80 },
  baseline: side(),
  with_plan: side({
    it_power_kw: 475,
    power_headroom_kw: 25,
    cooling_headroom_kw: 75,
    thermal_margin_C: 6.7,
    status: { power: "tight", cooling: "ok", thermal: "ok" },
    overall: "tight",
  }),
  verdict: "fits_with_little_margin",
  racks_that_fit: { by_power: 13, by_cooling: 19, limit: 13, note: "Power and cooling only; thermal margin is checked for the requested plan, not searched." },
  ...over,
});
