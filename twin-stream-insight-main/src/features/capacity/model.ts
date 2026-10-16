/**
 * Task 26: pure view-model for the capacity planner. No React, no network, no clock.
 *
 * Everything shown is the backend's model-based estimate on simulated data. The backend has no per-rack or per-zone
 * limits, so headroom here is a FACILITY figure; the only client-side arithmetic is the even split across zones used
 * by the 3D overlay (`three/headroomOverlay.ts`), which is labelled as an assumption.
 */
import type { HeadroomStatus } from "@/three/headroomOverlay";
import type { Capacity, CapacitySide } from "./schema";

/** Mirrors `MAX_ADD_RACKS` and `KW_PER_RACK_BOUNDS` in src/capacity/planner.py (the backend rejects anything else). */
export const PLAN_BOUNDS = { maxRacks: 200, minKwPerRack: 0.1, maxKwPerRack: 60 } as const;
export const DEFAULT_PLAN: Plan = { addRacks: 10, kwPerRack: 8 };
export const ESTIMATE_LABEL = "model-based estimate";

export interface Plan {
  addRacks: number;
  kwPerRack: number;
}
export interface PlanErrors {
  racks?: string;
  kw?: string;
}

/** Validate what the person typed. Nothing is clamped or rounded: an invalid field is named instead. */
export function parsePlan(racks: string, kw: string): { ok: true; plan: Plan } | { ok: false; errors: PlanErrors } {
  const errors: PlanErrors = {};
  const r = racks.trim();
  const k = kw.trim();
  const n = /^\d+$/.test(r) ? Number(r) : NaN;
  if (!Number.isInteger(n) || n > PLAN_BOUNDS.maxRacks) errors.racks = `Enter a whole number from 0 to ${PLAN_BOUNDS.maxRacks}.`;
  const v = /^\d+(\.\d+)?$/.test(k) ? Number(k) : NaN;
  if (!Number.isFinite(v) || v < PLAN_BOUNDS.minKwPerRack || v > PLAN_BOUNDS.maxKwPerRack)
    errors.kw = `Enter a number from ${PLAN_BOUNDS.minKwPerRack} to ${PLAN_BOUNDS.maxKwPerRack} kW.`;
  return errors.racks || errors.kw ? { ok: false, errors } : { ok: true, plan: { addRacks: n, kwPerRack: v } };
}

export type CellStatus = HeadroomStatus | "unknown";
export const STATUS_CUE: Readonly<Record<CellStatus, { glyph: string; word: string }>> = {
  ok: { glyph: "●", word: "ok" },
  tight: { glyph: "▲", word: "tight" },
  exceeded: { glyph: "■", word: "exceeded" },
  unknown: { glyph: "?", word: "not modelled" },
};

export const VERDICT_TEXT: Readonly<Record<Capacity["verdict"], string>> = {
  fits: "Fits",
  fits_with_little_margin: "Fits with little margin",
  does_not_fit: "Does not fit",
};

export function verdictSentence(c: Capacity): string {
  const { add_racks, kw_per_rack } = c.plan;
  if (add_racks === 0) return `Current headroom (${ESTIMATE_LABEL}): ${VERDICT_TEXT[c.verdict].toLowerCase()} as is.`;
  return `${add_racks} more rack${add_racks === 1 ? "" : "s"} at ${kw_per_rack} kW: ${VERDICT_TEXT[c.verdict].toLowerCase()} (${ESTIMATE_LABEL}).`;
}

export interface Row {
  key: "power" | "cooling" | "thermal" | "inlet";
  label: string;
  unit: "kW" | "°C";
  /** The limit the headroom is measured against, or null when it is not modelled / not a capacity. */
  limit: number | null;
  now: number | null;
  withPlan: number | null;
  nowStatus: CellStatus;
  planStatus: CellStatus;
}

export function rows(c: Capacity): Row[] {
  const b: CapacitySide = c.baseline;
  const p: CapacitySide = c.with_plan;
  return [
    { key: "power", label: "Power headroom (IT)", unit: "kW", limit: b.power_limit_kw, now: b.power_headroom_kw, withPlan: p.power_headroom_kw, nowStatus: b.status.power, planStatus: p.status.power },
    { key: "cooling", label: "Cooling headroom", unit: "kW", limit: b.cooling_capacity_kw, now: b.cooling_headroom_kw, withPlan: p.cooling_headroom_kw, nowStatus: b.status.cooling, planStatus: p.status.cooling },
    { key: "thermal", label: "Thermal margin (server outlet)", unit: "°C", limit: null, now: b.thermal_margin_C, withPlan: p.thermal_margin_C, nowStatus: b.status.thermal, planStatus: p.status.thermal },
    { key: "inlet", label: "Inlet margin (information)", unit: "°C", limit: null, now: b.inlet_margin_C, withPlan: p.inlet_margin_C, nowStatus: "unknown", planStatus: "unknown" },
  ];
}

/** A number with its unit, or an explicit "not modelled" (never a blank or a 0). */
export function fmt(v: number | null, unit: string): string {
  return v === null ? "not modelled" : `${v.toFixed(1)} ${unit}`;
}

/** What the 3D overlay shows for a result: the plan's worst status and facility headroom totals. Null while no result. */
export function overlayPatch(c: Capacity | null): { status: HeadroomStatus | null; powerKw: number | null; coolingKw: number | null } {
  if (!c) return { status: null, powerKw: null, coolingKw: null };
  return { status: c.with_plan.overall, powerKw: c.with_plan.power_headroom_kw, coolingKw: c.with_plan.cooling_headroom_kw };
}
