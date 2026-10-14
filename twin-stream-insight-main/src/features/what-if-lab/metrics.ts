/** Task 15: the four comparison metrics and the delta arithmetic. PURE. Every value is the backend's own output; this file only subtracts. */
import type { WhatIfResponse } from "@/api/apiClient";
import { OUTLET_SCALE } from "@/three/thermalMapping";

/** The twin's hard outlet ceiling (`OUTLET_TEMP_MAX`, 45 °C), the same constant the 3D thermal scale uses. */
export const OUTLET_LIMIT_C = OUTLET_SCALE.max;

export const METRICS = [
  { id: "energy", label: "Energy (24 h)", unit: "kWh", precision: 0, sweepKey: "total_energy_kwh" },
  { id: "pue", label: "Mean PUE", unit: "", precision: 3, sweepKey: "mean_pue" },
  { id: "carbon", label: "CO₂ (24 h)", unit: "kg", precision: 0, sweepKey: "total_co2_kg" },
  { id: "margin", label: "Thermal margin", unit: "°C", precision: 1, sweepKey: "thermal_margin_C" },
] as const;
export type MetricId = (typeof METRICS)[number]["id"];
export type MetricValues = Readonly<Record<MetricId, number>>;

export const CARBON_FALLBACK_LABEL = "Fallback grid intensity (assumed flat value), not real grid data";
export const ESTIMATE_LABEL = "model estimate on simulated data";

/** Thermal margin = the twin's outlet ceiling minus the hottest outlet temperature of the 24 h run. Negative = the run exceeds the ceiling. */
export const thermalMargin = (maxOutletC: number, limitC: number = OUTLET_LIMIT_C): number => limitC - maxOutletC;

export function readMetrics(r: Pick<WhatIfResponse, "total_energy_kwh" | "mean_pue" | "total_co2_kg" | "max_outlet_temp_C">): MetricValues {
  return { energy: r.total_energy_kwh, pue: r.mean_pue, carbon: r.total_co2_kg, margin: thermalMargin(r.max_outlet_temp_C) };
}

export interface Delta {
  readonly base: number;
  readonly scenario: number;
  /** scenario - base */
  readonly delta: number;
  /** null when the baseline is 0 (a percentage of zero is undefined). */
  readonly pct: number | null;
  readonly direction: "up" | "down" | "same";
}

export function deltaOf(base: number, scenario: number): Delta {
  const delta = scenario - base;
  // Differences below display precision of float noise are "same": compare with a relative epsilon.
  const same = Math.abs(delta) <= 1e-9 * Math.max(1, Math.abs(base), Math.abs(scenario));
  return {
    base,
    scenario,
    delta: same ? 0 : delta,
    pct: base === 0 ? null : same ? 0 : (delta / Math.abs(base)) * 100,
    direction: same ? "same" : delta > 0 ? "up" : "down",
  };
}

export function deltasOf(base: MetricValues, scenario: MetricValues): Record<MetricId, Delta> {
  return Object.fromEntries(METRICS.map((m) => [m.id, deltaOf(base[m.id], scenario[m.id])])) as Record<MetricId, Delta>;
}

export const fixed = (v: number, precision: number): string => v.toFixed(precision);
export function signed(v: number, precision: number): string {
  const text = Math.abs(v).toFixed(precision);
  return v > 0 && Number(text) !== 0 ? `+${text}` : v < 0 && Number(text) !== 0 ? `−${text}` : text;
}
export const signedPct = (pct: number | null): string => (pct === null ? "n/a (baseline is 0)" : `${signed(pct, 1)}%`);

export const DIRECTION_WORD = { up: { glyph: "▲", word: "higher" }, down: { glyph: "▼", word: "lower" }, same: { glyph: "＝", word: "unchanged" } } as const;
