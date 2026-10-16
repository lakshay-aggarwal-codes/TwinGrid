/** Test fixtures only (not imported by the app). Shapes mirror `GET /api/carbon/schedule`. */
import type { CarbonSchedule } from "./schema";

const RAMP = Array.from({ length: 24 }, (_, h) => 300 + h);
const FLAT = Array.from({ length: 24 }, () => 475);
const SYNTH = Array.from({ length: 24 }, (_, h) => 475 - 120 * Math.cos((2 * Math.PI * (h - 13)) / 24));

const base = (): Pick<CarbonSchedule, "label" | "basis" | "site_timezone" | "inputs" | "caveats"> => ({
  label: "scheduling suggestion from an hour-of-day carbon profile, not a forecast",
  basis: "BASIS TEXT",
  site_timezone: "UTC",
  inputs: { duration_h: 4, load_kw: 100, window_start: 0, window_hours: 24, reference_start_hour: null },
  caveats: [],
});

/** A documented, varying series (300 + hour). */
export const varying = (): CarbonSchedule => ({
  ...base(),
  profile: "data",
  status: "ok",
  headline: "Lowest-carbon 4-hour window: 00:00 to 04:00 (site-local time)",
  message: "Hours of the day with lower carbon intensity in the loaded series. This is a usual pattern, not a forecast for a particular day.",
  synthetic_label: null,
  carbon: { is_fallback: false, semantic: "average", statement: "Carbon term uses an average-intensity series.", time_varying_signal: true },
  curve_gco2_per_kwh: RAMP,
  best: { start_hour: 0, end_hour: 4, mean_gco2_per_kwh: 301.5, emissions_kg: 120.6 },
  worst: { start_hour: 20, end_hour: 0, mean_gco2_per_kwh: 321.5, emissions_kg: 128.6 },
  baseline: { kind: "average_of_allowed_windows", start_hour: null, end_hour: null, mean_gco2_per_kwh: 311.5, emissions_kg: 124.6 },
  savings: { emissions_kg: 4, pct: 3.2 },
  caveats: ["Average intensity is not marginal intensity: the real-world effect of moving load may differ."],
});

/** The flat assumed constant: nothing may be claimed. */
export const flat = (): CarbonSchedule => ({
  ...base(),
  profile: "data",
  status: "no_variation",
  headline: "No carbon variation in current data",
  message: "No carbon variation in current data. The carbon signal is the flat assumed constant, not grid data, so every hour looks the same: no window is better than another and no saving is claimed.",
  synthetic_label: null,
  carbon: { is_fallback: true, semantic: "constant_assumption", statement: "Carbon term present; the signal is an assumption (a flat assumed intensity), not measured grid data.", time_varying_signal: false },
  curve_gco2_per_kwh: FLAT,
  best: null,
  worst: null,
  baseline: null,
  savings: null,
});

export const unverified = (): CarbonSchedule => ({
  ...flat(),
  status: "unverified",
  headline: "Carbon data is incomplete or unverified",
  message: "Carbon data is incomplete or unverified: some hours of the day have no data and are filled by an assumption, so no window and no saving is suggested.",
  carbon: { is_fallback: true, semantic: "average", statement: "Carbon term present; the signal is an assumption (a flat assumed intensity), not measured grid data.", time_varying_signal: false },
  curve_gco2_per_kwh: null,
});

export const synthetic = (): CarbonSchedule => ({
  ...varying(),
  profile: "synthetic_demo",
  status: "synthetic_demo",
  headline: "Demonstration only: Lowest-carbon 4-hour window: 11:00 to 15:00 (site-local time)",
  message: "SYNTHETIC DEMONSTRATION profile, not grid data. The curve is made up to show how the suggestion works.",
  synthetic_label: "SYNTHETIC DEMONSTRATION profile, not grid data",
  carbon: { is_fallback: true, semantic: "constant_assumption", statement: "Carbon term present; the signal is an assumption (a flat assumed intensity), not measured grid data.", time_varying_signal: false },
  curve_gco2_per_kwh: SYNTH,
  best: { start_hour: 11, end_hour: 15, mean_gco2_per_kwh: 360, emissions_kg: 144 },
  caveats: ["Synthetic profile: not grid data, not a forecast."],
});
