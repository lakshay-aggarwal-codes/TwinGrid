import type { StateResponse } from "@/api/apiClient";

/**
 * 'thermal' is Stage 7's mode -- its coloring lives entirely in
 * thermalMapping.ts (real inlet/outlet values, rendered as two rack halves)
 * rather than here, since it needs two colors per rack, not one uniform
 * tint. getModeColor()/getModeReadings() below intentionally don't handle
 * it -- Rack.tsx and ModeLegend.tsx branch to thermalMapping.ts directly
 * for that case.
 */
export type VisualizationMode = "physical" | "thermal" | "energy" | "cooling" | "sustainability";

export const MODE_LABELS: Record<VisualizationMode, string> = {
  physical: "Physical",
  thermal: "Thermal",
  energy: "Energy",
  cooling: "Cooling",
  sustainability: "Sustainability",
};

export interface ModeColor {
  /** Uniform tint applied to every rack's idle face -- facility-wide only,
   * never varied per rack (see the Stage 0 audit + Stage 6's FloorHeatmap
   * fix: there is no per-rack backend data to justify spatial variation). */
  base: string;
  /** Slightly brighter variant used for hover/selected so those states
   * still read clearly against a colored fill. */
  emphasis: string;
}

const NEUTRAL: ModeColor = { base: "#2a2a2f", emphasis: "#3a3a42" };

// Industry-standard-ish bands for real, well-known ratios (PUE, WUE) --
// these thresholds interpret a real number, they don't invent one.
function pueColor(pue: number): ModeColor {
  if (pue <= 1.2) return { base: "#0e3d33", emphasis: "#16a34a" };
  if (pue <= 1.5) return { base: "#123a1f", emphasis: "#4ade80" };
  if (pue <= 2.0) return { base: "#4a3410", emphasis: "#f59e0b" };
  return { base: "#4a1414", emphasis: "#ef4444" };
}

function wueColor(wue: number): ModeColor {
  if (wue <= 1.0) return { base: "#0e3d33", emphasis: "#16a34a" };
  if (wue <= 1.8) return { base: "#123a1f", emphasis: "#4ade80" };
  if (wue <= 2.5) return { base: "#4a3410", emphasis: "#f59e0b" };
  return { base: "#4a1414", emphasis: "#ef4444" };
}

// One real, backend-provided categorical value (cooling_mode) mapped to a
// fixed, consistent color per category -- not fabricated per-rack data.
const COOLING_MODE_COLOR: Record<string, ModeColor> = {
  free_air: { base: "#123a1f", emphasis: "#4ade80" },
  closed_loop: { base: "#123047", emphasis: "#38bdf8" },
  evaporative: { base: "#0e3d33", emphasis: "#2dd4bf" },
  hybrid: { base: "#2f1f47", emphasis: "#a78bfa" },
};

/**
 * The single facility-wide color every rack shares while `mode` is active.
 * Returns NEUTRAL (desaturated) before liveState arrives -- never a guess.
 */
export function getModeColor(mode: VisualizationMode, liveState: StateResponse | null): ModeColor {
  if (mode === "physical" || mode === "thermal" || !liveState) return NEUTRAL;
  switch (mode) {
    case "energy":
      return pueColor(liveState.pue);
    case "cooling":
      return COOLING_MODE_COLOR[liveState.cooling_mode] ?? NEUTRAL;
    case "sustainability":
      return wueColor(liveState.wue);
    default:
      return NEUTRAL;
  }
}

export interface ModeReading {
  label: string;
  value: string;
}

/**
 * The real numbers shown in the legend for the active mode. Always
 * facility-wide, always labeled as such by the legend component -- this
 * function only supplies the values, not the "facility-wide" framing.
 */
export function getModeReadings(mode: VisualizationMode, liveState: StateResponse | null): ModeReading[] {
  if (!liveState) return [];
  switch (mode) {
    case "energy":
      return [
        { label: "PUE", value: liveState.pue.toFixed(2) },
        { label: "IT Power", value: `${liveState.it_power_kw.toFixed(0)} kW` },
        { label: "Cooling Power", value: `${liveState.cooling_power_kw.toFixed(0)} kW` },
        { label: "Total Power", value: `${liveState.total_power_kw.toFixed(0)} kW` },
      ];
    case "cooling":
      return [
        { label: "Mode", value: liveState.cooling_mode },
        { label: "Cooling Power", value: `${liveState.cooling_power_kw.toFixed(0)} kW` },
        { label: "Water Flow", value: `${liveState.water_flow_lpm.toFixed(1)} L/min` },
        { label: "Water Pressure", value: `${liveState.water_pressure_bar.toFixed(2)} bar` },
      ];
    case "sustainability": {
      const readings: ModeReading[] = [
        { label: "WUE", value: liveState.wue.toFixed(3) },
        { label: "Water Consumed", value: `${liveState.water_consumed_L.toFixed(0)} L` },
      ];
      // Carbon intensity is only shown when the backend flags it as real --
      // otherwise it's a flat fallback constant and would be misleading
      // presented as live grid data (see apiClient.ts's StateResponse comment).
      if (liveState.carbon_data_is_real && liveState.carbon_intensity_gco2_per_kwh !== undefined) {
        readings.push({ label: "Carbon Intensity", value: `${liveState.carbon_intensity_gco2_per_kwh.toFixed(0)} gCO₂/kWh` });
      }
      if (liveState.drought_override_active) {
        readings.push({ label: "Drought Override", value: "Active" });
      }
      return readings;
    }
    default:
      return [];
  }
}

/** Whether the sustainability legend should disclose the carbon-fallback caveat. */
export function isCarbonDataFallback(liveState: StateResponse | null): boolean {
  return liveState?.carbon_data_is_real === false;
}
