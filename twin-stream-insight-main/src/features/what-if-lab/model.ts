/**
 * Task 15: what-if lab inputs. PURE.
 *
 * The four controls are the four inputs the backend's `GET /api/whatif` accepts that the lab exposes. IT load and
 * ambient ranges mirror the backend's (`api/services/scenario_registry.py`); the backend still validates every request,
 * so a drift here shows up as a 422, never as a wrong number. The set-point range is NOT a constant: it depends on the
 * physics the server runs (legacy-0 5-15 C, physics 1 16-25 C), so it is read from the server (`setpoint_check` on
 * `GET /api/optimizer/baseline-recommendation`, the same field the recommendation form uses) and passed in as a
 * `SetpointRange`. Water stress is not a lab control: it is held at the backend default (0) in every run, and the lab
 * says so.
 */
import type { WhatIfParams } from "@/api/apiClient";
import { setpointCheckOf } from "../optimizer-approvals/model";

export const COOLING_MODES = [
  { id: "auto", label: "Auto (rule-based)" },
  { id: "free_air", label: "Free air" },
  { id: "closed_loop", label: "Closed loop" },
  { id: "evaporative", label: "Evaporative" },
  { id: "hybrid", label: "Hybrid" },
] as const;
export type CoolingModeId = (typeof COOLING_MODES)[number]["id"];

/** IT load is shown as a percentage and sent as a 0-1 fraction (ADR 004). */
export interface LabInputs {
  readonly itLoadPct: number;
  readonly ambientC: number;
  readonly setpointC: number;
  readonly mode: CoolingModeId;
}

/** Controls whose range is fixed by the backend's registry. */
export const LAB_BOUNDS = {
  itLoadPct: { min: 0, max: 100, step: 1, unit: "%" },
  ambientC: { min: -10, max: 50, step: 0.5, unit: "°C" },
} as const;
export type FixedKey = keyof typeof LAB_BOUNDS;

/** The chilled-water set-point range the server's physics accepts for the lab, and where it came from. */
export interface SetpointRange {
  readonly min: number;
  readonly max: number;
  readonly step: number;
  readonly unit: string;
  /** The server's `physics_version`, when it said which. */
  readonly physics: string | null;
}

export const SETPOINT_STEP_C = 0.5;

/** The backend's own what-if default set-point (`WHATIF_DEFAULTS["chilled_water_temp"]`). It is a default, not a bound: it is clamped into the range. */
export const BACKEND_WHATIF_SETPOINT_C = 7;

/**
 * The set-point range from an optimizer effect payload's `setpoint_check.actuator_range_C`. Null when the server sent
 * no usable range (absent, malformed or empty): the lab then has no range and says so; it never falls back to a constant.
 */
export function setpointRangeOf(effect: object | null | undefined): SetpointRange | null {
  const check = setpointCheckOf(effect);
  if (check === null || check.actuatorRange === null) return null;
  const [lo, hi] = check.actuatorRange;
  if (!(lo < hi)) return null;
  return { min: lo, max: hi, step: SETPOINT_STEP_C, unit: "°C", physics: check.physics };
}

/** The backend defaults, with the set-point moved into `range` (7 under legacy-0; the bottom of the range under physics 1). */
export function defaultInputs(range: SetpointRange): LabInputs {
  return {
    itLoadPct: 65,
    ambientC: 22,
    setpointC: Math.min(range.max, Math.max(range.min, BACKEND_WHATIF_SETPOINT_C)),
    mode: "auto",
  };
}

export const WATER_STRESS_HELD = 0;

export const isMode = (v: unknown): v is CoolingModeId => COOLING_MODES.some((m) => m.id === v);
export const modeLabel = (id: string): string => COOLING_MODES.find((m) => m.id === id)?.label ?? id;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round = (v: number, step: number) => Math.round(v / step) * step;

/** Snap a number to a fixed control's range and step; NaN falls back to `fallback`. */
export function snap(key: FixedKey, v: number, fallback: number): number {
  if (!Number.isFinite(v)) return fallback;
  const b = LAB_BOUNDS[key];
  return clamp(Math.round(round(v, b.step) * 1000) / 1000, b.min, b.max);
}

/** Snap a set-point to the server's range and step; NaN falls back to `fallback`. */
export function snapSetpoint(v: number, range: SetpointRange, fallback: number): number {
  if (!Number.isFinite(v)) return fallback;
  return clamp(Math.round(round(v, range.step) * 1000) / 1000, range.min, range.max);
}

export function normalise(i: Partial<LabInputs>, range: SetpointRange): LabInputs {
  const d = defaultInputs(range);
  return {
    itLoadPct: snap("itLoadPct", i.itLoadPct ?? d.itLoadPct, d.itLoadPct),
    ambientC: snap("ambientC", i.ambientC ?? d.ambientC, d.ambientC),
    setpointC: snapSetpoint(i.setpointC ?? d.setpointC, range, d.setpointC),
    mode: isMode(i.mode) ? i.mode : d.mode,
  };
}

export const inputsEqual = (a: LabInputs, b: LabInputs): boolean =>
  a.itLoadPct === b.itLoadPct && a.ambientC === b.ambientC && a.setpointC === b.setpointC && a.mode === b.mode;

/** The request for `GET /api/whatif` (and the sweep). The query key `['whatif', params]` matches the existing What-If tab, so equal inputs share a cache entry. */
export function toParams(i: LabInputs): WhatIfParams {
  return {
    utilisation: Math.round(i.itLoadPct * 10) / 1000, // pct -> fraction without float noise (65 -> 0.65)
    outside_temp: i.ambientC,
    water_stress: WATER_STRESS_HELD,
    mode: i.mode,
    chilled_water_temp: i.setpointC,
  };
}

export const describeInputs = (i: LabInputs): string => `${i.itLoadPct}% IT load, ${i.ambientC} °C ambient, ${i.setpointC} °C setpoint, ${modeLabel(i.mode)}`;
