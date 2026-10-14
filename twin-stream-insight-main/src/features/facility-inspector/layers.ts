import type { VisualizationMode } from "@/three/visualizationModes";

/**
 * Task 13: the four scene layers as toggles. They drive the scene's EXISTING visualization modes (one tint at a time), so
 * nothing new is drawn and nothing implies per-rack data: every layer is a facility-wide value shown on every rack.
 *
 *   thermal -> "thermal"        two-tone rack: lower half = server inlet, upper half = server outlet
 *   airflow -> "cooling"        tint by cooling_mode (there is no airflow measurement; this is the cooling mode)
 *   power   -> "energy"         tint by PUE band
 *   carbon  -> "sustainability" tint by WUE band; carbon intensity is listed only when the backend says it is real
 */
export const LAYER_IDS = ["thermal", "airflow", "power", "carbon"] as const;
export type LayerId = (typeof LAYER_IDS)[number];

export interface LayerDef {
  id: LayerId;
  label: string;
  mode: Exclude<VisualizationMode, "physical">;
  /** One honest sentence for the legend. */
  note: string;
}

export const LAYERS: readonly LayerDef[] = [
  { id: "thermal", label: "Thermal", mode: "thermal", note: "Server inlet (lower half) and outlet (upper half) temperature. Facility-wide, same on every rack." },
  { id: "airflow", label: "Airflow", mode: "cooling", note: "Shows the facility cooling mode; the backend has no airflow measurement. Same on every rack." },
  { id: "power", label: "Power", mode: "energy", note: "Tinted by facility PUE band. Same on every rack." },
  { id: "carbon", label: "Carbon", mode: "sustainability", note: "Tinted by facility WUE band (water); carbon intensity is listed only when the backend flags it as real. Same on every rack." },
];

export function layerForMode(mode: VisualizationMode): LayerId | null {
  return LAYERS.find((l) => l.mode === mode)?.id ?? null;
}

/** Toggling the active layer off returns to the plain (physical) view; toggling another switches to it. */
export function modeAfterToggle(current: VisualizationMode, layer: LayerId): VisualizationMode {
  const def = LAYERS.find((l) => l.id === layer);
  if (!def) return current;
  return current === def.mode ? "physical" : def.mode;
}

/** A legend entry. `glyph` is the non-colour cue (a shape character) shown next to the colour swatch and the text. */
export interface LegendEntry {
  key: string;
  glyph: string;
  text: string;
  /** Only meaningful when a current value exists. */
  active?: boolean;
}

/** Band edges mirror `pueColor` / `wueColor` in visualizationModes.ts (a test pins them to getModeColor). */
export const PUE_BANDS = [
  { max: 1.2, glyph: "●", text: "PUE ≤ 1.2 · low overhead" },
  { max: 1.5, glyph: "◆", text: "PUE 1.2–1.5 · moderate" },
  { max: 2.0, glyph: "▲", text: "PUE 1.5–2.0 · elevated" },
  { max: Infinity, glyph: "■", text: "PUE > 2.0 · high" },
] as const;

export const WUE_BANDS = [
  { max: 1.0, glyph: "●", text: "WUE ≤ 1.0 · low water use" },
  { max: 1.8, glyph: "◆", text: "WUE 1.0–1.8 · moderate" },
  { max: 2.5, glyph: "▲", text: "WUE 1.8–2.5 · elevated" },
  { max: Infinity, glyph: "■", text: "WUE > 2.5 · high" },
] as const;

export const COOLING_MODES: readonly { id: string; glyph: string; text: string }[] = [
  { id: "free_air", glyph: "F", text: "free_air" },
  { id: "closed_loop", glyph: "C", text: "closed_loop" },
  { id: "evaporative", glyph: "E", text: "evaporative" },
  { id: "hybrid", glyph: "H", text: "hybrid" },
];

export function bandIndex(bands: readonly { max: number }[], value: number): number {
  const i = bands.findIndex((b) => value <= b.max);
  return i === -1 ? bands.length - 1 : i;
}

export interface LegendInput {
  pue?: number;
  wue?: number;
  coolingMode?: string;
  inletTempC?: number;
  outletTempC?: number;
}

/** Legend rows for a layer. `values` is null whenever there is no CURRENT reading: then nothing is marked active. */
export function legendFor(layer: LayerId, values: LegendInput | null): LegendEntry[] {
  switch (layer) {
    case "thermal":
      return [
        { key: "outlet", glyph: "▲", text: `Upper half · server outlet${values?.outletTempC !== undefined ? ` ${values.outletTempC.toFixed(1)} °C` : ""}` },
        { key: "inlet", glyph: "▼", text: `Lower half · server inlet${values?.inletTempC !== undefined ? ` ${values.inletTempC.toFixed(1)} °C` : ""}` },
      ];
    case "power": {
      const at = values?.pue !== undefined ? bandIndex(PUE_BANDS, values.pue) : -1;
      return PUE_BANDS.map((b, i) => ({ key: `pue-${i}`, glyph: b.glyph, text: b.text, active: i === at }));
    }
    case "carbon": {
      const at = values?.wue !== undefined ? bandIndex(WUE_BANDS, values.wue) : -1;
      return WUE_BANDS.map((b, i) => ({ key: `wue-${i}`, glyph: b.glyph, text: b.text, active: i === at }));
    }
    case "airflow":
      return COOLING_MODES.map((m) => ({ key: m.id, glyph: m.glyph, text: m.text, active: values?.coolingMode === m.id }));
  }
}
