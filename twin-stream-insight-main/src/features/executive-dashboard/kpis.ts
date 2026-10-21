import type { WhatIfResponse } from "@/api/apiClient";
import type { EvaluationResult } from "@/evaluation/schema";
import { fmtNumber } from "./format";
import type { LiveSample } from "./liveSeries";

/**
 * Task 16: view-models of the five KPI cards. A value the data does not support is `not-measured`, never 0 and never
 * an estimate. Each card carries the basis it was computed on so a reader can tell a live tick from a 24 h model run.
 */

export const NOT_MEASURED = "NOT MEASURED";
export const MODEL_BASIS = "Model estimate on simulated data: an isolated 24 h run at the sidebar inputs.";

export type KpiId = "pue" | "it-energy" | "total-energy" | "carbon" | "savings";

export interface KpiView {
  readonly id: KpiId;
  readonly label: string;
  /** Number to show (and animate), or null when not measured. */
  readonly value: number | null;
  readonly decimals: number;
  readonly unit: string;
  /** Why the value is NOT MEASURED, when it is. */
  readonly reason: string | null;
  /** What the number is and where it comes from. */
  readonly basis: string;
  /** A caveat that must stay next to the number (e.g. fallback carbon). */
  readonly caveat: string | null;
  /** Words that give direction without colour (savings). */
  readonly direction: string | null;
}

const notMeasured = (id: KpiId, label: string, unit: string, decimals: number, reason: string, basis: string): KpiView => ({
  id, label, value: null, decimals, unit, reason, basis, caveat: null, direction: null,
});

export function pueKpi(latest: LiveSample | null, whatIf: WhatIfResponse | null): KpiView {
  const basis = `Latest live tick of the simulated feed${whatIf ? `; 24 h model mean PUE at the sidebar inputs: ${fmtNumber(whatIf.mean_pue, 2)}` : ""}.`;
  if (!latest) return notMeasured("pue", "PUE", "", 2, "No live frame has been received yet.", basis);
  return { id: "pue", label: "PUE", value: latest.pue, decimals: 2, unit: "", reason: null, basis, caveat: null, direction: null };
}

/**
 * The backend defines WUE as total water \u00f7 IT energy, so IT energy is that division, exactly (checked against the
 * twin in the tests). When WUE is 0 the division is undefined and IT energy is NOT MEASURED.
 */
export function itEnergyKwh(w: WhatIfResponse): number | null {
  if (!Number.isFinite(w.wue) || w.wue <= 0 || !Number.isFinite(w.total_water_L)) return null;
  const v = w.total_water_L / w.wue;
  return Number.isFinite(v) ? v : null;
}

export function itEnergyKpi(w: WhatIfResponse | null): KpiView {
  const basis = `${MODEL_BASIS} IT energy = total water \u00f7 WUE, the backend\u2019s own WUE definition (the response carries no IT-energy field).`;
  if (!w) return notMeasured("it-energy", "IT energy", "kWh/day", 0, "No model run is available.", basis);
  const v = itEnergyKwh(w);
  if (v === null) return notMeasured("it-energy", "IT energy", "kWh/day", 0, "WUE is 0 in this run, so IT energy cannot be recovered from it.", basis);
  return { id: "it-energy", label: "IT energy", value: v, decimals: 0, unit: "kWh/day", reason: null, basis, caveat: null, direction: null };
}

export function totalEnergyKpi(w: WhatIfResponse | null): KpiView {
  if (!w || !Number.isFinite(w.total_energy_kwh)) return notMeasured("total-energy", "Total energy", "kWh/day", 0, "No model run is available.", MODEL_BASIS);
  return { id: "total-energy", label: "Total energy", value: w.total_energy_kwh, decimals: 0, unit: "kWh/day", reason: null, basis: MODEL_BASIS, caveat: null, direction: null };
}

export const FALLBACK_CARBON_CAVEAT = "Fallback carbon intensity (an assumed flat value, not grid data).";

export function carbonKpi(w: WhatIfResponse | null): KpiView {
  if (!w || !Number.isFinite(w.total_co2_kg)) return notMeasured("carbon", "Carbon", "kg CO\u2082/day", 0, "No model run is available.", MODEL_BASIS);
  const real = w.carbon_data_is_real === true;
  return {
    id: "carbon",
    label: real ? "Carbon" : "Carbon (fallback)",
    value: w.total_co2_kg,
    decimals: 0,
    unit: "kg CO\u2082/day",
    reason: null,
    basis: MODEL_BASIS,
    caveat: real ? null : FALLBACK_CARBON_CAVEAT,
    direction: null,
  };
}

// ------------------------------------------------------------------------------------------------ savings

export interface SavingsFacts {
  readonly evaluationId: string;
  readonly baselineId: string;
  readonly comparedId: string;
  /** baseline energy minus compared energy (kWh); positive = the compared policy used less. */
  readonly savedKwh: number;
  readonly savedPct: number;
  /** `decision.claim_allowed`, verbatim. */
  readonly claimAllowed: string;
  readonly outcome: string;
}

const isBaselineController = (p: { policy_id: string; kind?: string }): boolean => p.kind === "rule" || p.policy_id === "rule";
const isPpo = (p: { policy_id: string; kind?: string }): boolean => /^ppo/i.test(p.kind ?? "") || /^ppo/i.test(p.policy_id);

/**
 * Baseline controller = the report's `rule` policy. Compared policy = the first PPO policy if the report has one,
 * otherwise the first other policy. Both energy figures are the backend's `energy_kwh`; this only subtracts them.
 * Null when the report has no baseline, no second policy, or no finite positive baseline energy.
 */
export function savingsFacts(r: EvaluationResult): SavingsFacts | null {
  const baseline = r.policies.find(isBaselineController);
  if (!baseline) return null;
  const others = r.policies.filter((p) => p !== baseline);
  const compared = others.find(isPpo) ?? others[0];
  if (!compared) return null;
  const b = baseline.metrics.energy_kwh;
  const c = compared.metrics.energy_kwh;
  if (typeof b !== "number" || typeof c !== "number" || !Number.isFinite(b) || !Number.isFinite(c) || b <= 0) return null;
  return {
    evaluationId: r.evaluation_id,
    baselineId: baseline.policy_id,
    comparedId: compared.policy_id,
    savedKwh: b - c,
    savedPct: ((b - c) / b) * 100,
    claimAllowed: r.decision.claim_allowed,
    outcome: r.decision.outcome,
  };
}

export function savingsKpi(facts: SavingsFacts | null, reason = "No policy-evaluation report with a baseline controller and a second policy is available."): KpiView {
  const label = "Savings vs baseline controller";
  if (!facts) {
    return notMeasured("savings", label, "%", 1, reason, "Read from a backend policy-evaluation report (simulated); nothing is estimated here.");
  }
  const pct = facts.savedPct;
  const direction = Math.abs(pct) < 0.05 ? "about the same energy as the baseline" : pct > 0 ? "less energy than the baseline" : "more energy than the baseline";
  return {
    id: "savings",
    label,
    value: Math.abs(pct),
    decimals: 1,
    unit: "%",
    reason: null,
    basis: `Simulated report ${facts.evaluationId}: policy \u201c${facts.comparedId}\u201d vs baseline controller \u201c${facts.baselineId}\u201d, backend energy_kwh (${fmtNumber(facts.savedKwh, 0)} kWh difference). Outcome ${facts.outcome}; claim allowed: ${facts.claimAllowed}.`,
    caveat: facts.claimAllowed === "none" ? "The report allows no performance claim; this is a simulated difference, not a validated saving." : null,
    direction,
  };
}

/** Newest report by `generated_at_utc` (ISO text sorts correctly); reports without a date come last; ties keep list order. */
export function newestEvaluationId(list: ReadonlyArray<{ evaluation_id?: string; generated_at_utc?: string | null }>): string | null {
  if (list.length === 0) return null;
  let best = list[0];
  for (const e of list.slice(1)) {
    const a = e.generated_at_utc ?? "";
    const b = best.generated_at_utc ?? "";
    if (a > b) best = e;
  }
  return best.evaluation_id ?? null; // optional only because the runtime-validated payload type is loose under strict:false
}

// ------------------------------------------------------------------------------------------------ sparklines

export interface SparkModel {
  readonly path: string;
  readonly min: number;
  readonly max: number;
  readonly latest: number;
  readonly count: number;
  readonly last: { x: number; y: number };
}

/** A plain polyline through the values in order: no smoothing, no resampling. Fewer than 2 finite values -> null. */
export function buildSpark(values: readonly number[], width: number, height: number): SparkModel | null {
  const v = values.filter((x) => Number.isFinite(x));
  if (v.length < 2) return null;
  let min = Infinity;
  let max = -Infinity;
  for (const x of v) {
    min = Math.min(min, x);
    max = Math.max(max, x);
  }
  const pad = 2;
  const x = (i: number) => Number((pad + (i / (v.length - 1)) * (width - 2 * pad)).toFixed(2));
  const y = (val: number) => Number((max === min ? height / 2 : height - pad - ((val - min) / (max - min)) * (height - 2 * pad)).toFixed(2));
  const pts = v.map((val, i) => ({ x: x(i), y: y(val) }));
  return { path: pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x} ${p.y}`).join(" "), min, max, latest: v[v.length - 1], count: v.length, last: pts[pts.length - 1] };
}
