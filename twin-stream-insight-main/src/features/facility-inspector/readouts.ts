import type { AlertRecord } from "@/api/apiClient";
import { utilisationToPercent } from "@/contract/units";
import { buildChartModel, buildSeries, formatUtc, type ChartModel } from "@/telemetry/history/model";
import type { HistoryData } from "@/telemetry/history/useTelemetryHistory";
import type { LiveStatePayload } from "@/api/apiClient";

/** Task 13: pure view-models for the rack inspector. No React, no clock, no network. */

/** The sparkline window. The history API has no per-rack sensor, so this is the facility outlet-temperature sensor. */
export const SPARK_MEASURAND = "server_outlet_temp_C";
export const SPARK_WINDOW_HOURS = 0.5;

export interface ReadingRow {
  id: "temperature" | "power" | "utilisation";
  label: string;
  /** Formatted value with its unit, or the literal `not reported`. */
  value: string;
}

/** Facility-wide values from the live frame. The backend reports no per-rack value, so these are the same for every rack. */
export function readingRows(state: LiveStatePayload): ReadingRow[] {
  const pct = utilisationToPercent(state.server_utilisation);
  return [
    { id: "temperature", label: "Server outlet temperature", value: Number.isFinite(state.server_outlet_temp_C) ? `${state.server_outlet_temp_C.toFixed(1)} °C` : "not reported" },
    { id: "power", label: "IT power", value: Number.isFinite(state.it_power_kw) ? `${state.it_power_kw.toFixed(1)} kW` : "not reported" },
    { id: "utilisation", label: "Server utilisation", value: pct === null ? "not reported" : `${pct.toFixed(0)} %` },
  ];
}

/** There is no per-rack health score on the backend; the UI must say so instead of showing a number. */
export const HEALTH_SCORE_TEXT = "NOT MEASURED";

/** Alerts the backend has not seen acknowledged. Facility-wide: the backend attributes no alert to a rack. */
export function openAlertCount(alerts: readonly AlertRecord[]): number {
  return alerts.filter((a) => !a.acknowledged).length;
}

export interface Sparkline {
  /** SVG path data, one per unbroken run of good samples (a backend-reported gap ends a run). */
  paths: string[];
  /** The last good point, for the end marker; null when there is none. */
  last: { x: number; y: number } | null;
  min: number;
  max: number;
  lastValue: number;
  unit: string | null;
  goodCount: number;
  fromLabel: string;
  toLabel: string;
  /** Samples left off the line (`invalid` or unrecognised quality). */
  excluded: number;
}

const PAD = 2;

/**
 * Draws only what the backend returned: good samples in backend order, a break at every reported gap, no smoothing,
 * no interpolation, no resampling. A flat series gets a mid-height line. No good sample -> null (the UI shows "empty").
 */
export function buildSparkline(data: HistoryData, width: number, height: number): Sparkline | null {
  const { series } = buildSeries({ sensorId: data.sensorId, unit: data.unit, items: data.items, gaps: data.gaps });
  const model: ChartModel = buildChartModel(series, data.gaps);
  const good = model.line.filter((p) => !p.gapBreak && p.v !== null);
  if (good.length === 0) return null;

  const t0 = good[0].t;
  const t1 = good[good.length - 1].t;
  let min = Infinity;
  let max = -Infinity;
  for (const p of good) {
    const v = p.v as number;
    min = Math.min(min, v);
    max = Math.max(max, v);
  }
  const x = (t: number) => (t1 === t0 ? width / 2 : PAD + ((t - t0) / (t1 - t0)) * (width - 2 * PAD));
  const y = (v: number) => (max === min ? height / 2 : height - PAD - ((v - min) / (max - min)) * (height - 2 * PAD));

  const paths: string[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length > 0) paths.push(run.join(" "));
    run = [];
  };
  let last: { x: number; y: number } | null = null;
  for (const p of model.line) {
    if (p.gapBreak || p.v === null) {
      flush();
      continue;
    }
    const px = Number(x(p.t).toFixed(2));
    const py = Number(y(p.v).toFixed(2));
    run.push(`${run.length === 0 ? "M" : "L"}${px} ${py}`);
    last = { x: px, y: py };
  }
  flush();

  return {
    paths,
    last,
    min,
    max,
    lastValue: good[good.length - 1].v as number,
    unit: data.unit,
    goodCount: good.length,
    fromLabel: formatUtc(t0),
    toLabel: formatUtc(t1),
    excluded: model.excluded.length,
  };
}
