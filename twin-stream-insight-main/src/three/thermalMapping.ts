/**
 * Thermal color mapping for the 3D twin's "Thermal" view mode.
 *
 * CRITICAL CONSTRAINT (see Stage 0 audit): the backend has no per-rack
 * thermal model. `/api/state` and the live WebSocket feed report exactly
 * one inlet temp, one outlet temp, one outside temp, one humidity --
 * facility-wide, not per-rack. Every function here is written to make that
 * hard to violate by accident: `computeThermalColors` takes a single
 * reading and returns a single pair of colors, meant to be applied
 * identically to every rack. There is no per-rack input anywhere in this
 * module, on purpose.
 */

/** The 'thermal' member of VisualizationMode (see three/visualizationModes.ts)
 * is what selects this module's coloring in Rack.tsx/Facility.tsx. */

export interface ThermalReading {
  inletTempC: number;
  outletTempC: number;
}

export interface ThermalColors {
  /** Color for the lower half of a rack -- cold-aisle intake side. */
  inlet: string;
  /** Color for the upper half of a rack -- hot-aisle exhaust side. */
  outlet: string;
}

/** Shown on every rack until the first live reading arrives -- neutral and
 * desaturated, never a guessed color (see non-negotiable #6). Also used as
 * the legend's "no data yet" swatch. */
export const WAITING_COLOR = "#3d4045";

type RGB = [number, number, number];

const COOL: RGB = [56, 189, 248]; // cyan-blue -- "cool" end of the scale
const AMBER: RGB = [245, 166, 35]; // warning
const CRITICAL: RGB = [222, 62, 52]; // red -- at/beyond the backend's own limit

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpRgb(a: RGB, b: RGB, t: number): RGB {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}

function toHex([r, g, b]: RGB): string {
  const c = (n: number) => Math.round(Math.max(0, Math.min(255, n))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

/**
 * A three-stop scale (cool -> warning -> critical) over a real temperature
 * range. `min` and `max` should be real, documented values where the
 * backend has them (see the scales below for exactly which numbers are
 * real backend constants vs. a chosen midpoint); `warnAt` is always a
 * chosen point between them, never a measured threshold.
 */
export interface ThermalScale {
  min: number;
  warnAt: number;
  max: number;
}

/**
 * Inlet (cold-aisle) scale. `min` (18°C) and `max` (27°C) are
 * `INLET_TEMP_MIN`/`INLET_TEMP_MAX` from the backend's own
 * `src/digital_twin.py` -- the twin's documented safe operating envelope,
 * not a guess. `warnAt` (24°C) is a chosen "getting close" point 3/4 of the
 * way through that real range; it is not itself a backend constant.
 */
export const INLET_SCALE: ThermalScale = { min: 18, warnAt: 24, max: 27 };

/**
 * Outlet (hot-aisle) scale. `max` (45°C) is `OUTLET_TEMP_MAX` from the same
 * source -- the twin's hard ceiling (the Phase-0 handoff notes outlet temp
 * was once observed exceeding it, which is exactly the kind of thing this
 * color should flag red for). `min` (28°C) and `warnAt` (38°C) are chosen
 * reference points, not backend constants -- there's no documented
 * "coolest normal outlet temp".
 */
export const OUTLET_SCALE: ThermalScale = { min: 28, warnAt: 38, max: 45 };

function scaleToColor(tempC: number, scale: ThermalScale): string {
  const { min, warnAt, max } = scale;
  if (tempC <= min) return toHex(COOL);
  if (tempC >= max) return toHex(CRITICAL);
  if (tempC <= warnAt) {
    const t = (tempC - min) / (warnAt - min);
    return toHex(lerpRgb(COOL, AMBER, t));
  }
  const t = (tempC - warnAt) / (max - warnAt);
  return toHex(lerpRgb(AMBER, CRITICAL, t));
}

/**
 * The single source of truth for "what color is thermal mode right now".
 * Returns null (never a guessed color) until a real reading exists --
 * callers should render `WAITING_COLOR` on every rack in that case.
 */
export function computeThermalColors(reading: ThermalReading | null): ThermalColors | null {
  if (!reading) return null;
  return {
    inlet: scaleToColor(reading.inletTempC, INLET_SCALE),
    outlet: scaleToColor(reading.outletTempC, OUTLET_SCALE),
  };
}

/** For the legend: color at a specific point along a scale, 0-1. */
export function scaleSwatchAt(scale: ThermalScale, t: number): string {
  const tempC = lerp(scale.min, scale.max, Math.max(0, Math.min(1, t)));
  return scaleToColor(tempC, scale);
}
