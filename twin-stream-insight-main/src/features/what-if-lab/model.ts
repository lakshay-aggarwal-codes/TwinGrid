/**
 * Task 15: what-if lab inputs. PURE.
 *
 * The four controls are the four inputs the backend's `GET /api/whatif` accepts that the lab exposes. Ranges and
 * defaults mirror the backend's (`api/services/scenario_registry.py`); the backend still validates every request, so a
 * drift here shows up as a 422, never as a wrong number. Water stress is not a lab control: it is held at the
 * backend default (0) in every run, and the lab says so.
 */
import type { WhatIfParams } from "@/api/apiClient";

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

export const LAB_BOUNDS = {
  itLoadPct: { min: 0, max: 100, step: 1, unit: "%" },
  ambientC: { min: -10, max: 50, step: 0.5, unit: "°C" },
  setpointC: { min: 5, max: 15, step: 0.5, unit: "°C" },
} as const;

/** The backend's documented what-if defaults (utilisation 0.65, outside 22 °C, chilled water 7 °C, mode auto). */
export const DEFAULT_INPUTS: LabInputs = { itLoadPct: 65, ambientC: 22, setpointC: 7, mode: "auto" };

export const WATER_STRESS_HELD = 0;

export const isMode = (v: unknown): v is CoolingModeId => COOLING_MODES.some((m) => m.id === v);
export const modeLabel = (id: string): string => COOLING_MODES.find((m) => m.id === id)?.label ?? id;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round = (v: number, step: number) => Math.round(v / step) * step;

/** Snap a number to a control's range and step; NaN falls back to `fallback`. */
export function snap(key: keyof typeof LAB_BOUNDS, v: number, fallback: number): number {
  if (!Number.isFinite(v)) return fallback;
  const b = LAB_BOUNDS[key];
  return clamp(Math.round(round(v, b.step) * 1000) / 1000, b.min, b.max);
}

export function normalise(i: Partial<LabInputs>): LabInputs {
  return {
    itLoadPct: snap("itLoadPct", i.itLoadPct ?? DEFAULT_INPUTS.itLoadPct, DEFAULT_INPUTS.itLoadPct),
    ambientC: snap("ambientC", i.ambientC ?? DEFAULT_INPUTS.ambientC, DEFAULT_INPUTS.ambientC),
    setpointC: snap("setpointC", i.setpointC ?? DEFAULT_INPUTS.setpointC, DEFAULT_INPUTS.setpointC),
    mode: isMode(i.mode) ? i.mode : DEFAULT_INPUTS.mode,
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
