/**
 * FE-02: the shapes the rest of the app already consumes, plus the adapters that produce them from the
 * validated contract layer (`src/contract`).
 *
 * Consumers (components, hooks, three/) are out of scope for FE-02 and still import these names from
 * `@/api/apiClient`. The adapters keep backend vocabulary verbatim: an enum value this frontend does not know
 * is passed on as its raw string (never mapped to a known value). FE-03/05 move consumers onto the contract
 * types, which keep the branded `Unknown`.
 */
import { isUnknown, type Unknown } from '../contract/schemas/common';
import type * as C from '../contract';

export interface StateResponse {
  timestamp: string;
  server_utilisation: number;
  outside_temp_C: number;
  server_inlet_temp_C: number;
  server_outlet_temp_C: number;
  it_power_kw: number;
  cooling_power_kw: number;
  total_power_kw: number;
  pue: number;
  water_flow_lpm: number;
  water_consumed_L: number;
  wue: number;
  humidity_pct: number;
  water_pressure_bar: number;
  cooling_mode: string;
  anomaly: number;
  water_stress?: number;
  carbon_intensity_gco2_per_kwh?: number;
  carbon_gco2?: number;
  drought_override_active?: boolean;
  /** false = flat 475 gCO2/kWh fallback (no data/cleaned/carbon_intensity.csv), not real grid data */
  carbon_data_is_real?: boolean;
}

/** Server-owned anomaly pipeline state (backend T3). The browser never scores anything itself. */
export type AnomalyPipelineStatus = 'warming_up' | 'ok' | 'anomalous' | 'unavailable' | 'error' | (string & {});

export interface AnomalyStatusPayload {
  status: AnomalyPipelineStatus;
  message: string;
  /** Reconstruction error of the last scored window; null unless status is ok/anomalous. */
  score: number | null;
  /** The detector's own trained threshold (unchanged by the pipeline). */
  threshold: number | null;
  type: string | null;
  window_size?: number;
  window_filled?: number;
  /** Tick seq of the newest sample in the scored window. */
  seq?: number | null;
  /** Lowest-evidence origin in the window. */
  origin?: string | null;
  detector_id?: string;
  model_version?: string | null;
  /** "synthetic" while the shipped detector has no real training data (roadmap D-4). */
  trained_on?: string;
  episode?: {
    open: boolean;
    dedupe_key: string | null;
    alert_id: number | null;
    start_seq: number | null;
    severity: string | null;
  };
  scored_at?: string;
}

/** One /ws/live payload: StateResponse plus the additive provenance/time fields. All optional (older backend). */
export interface LiveStatePayload extends StateResponse {
  schema_version?: number;
  /** Where the values come from. Only "simulated" exists today. */
  origin?: string;
  /** Strictly +1 per broadcast tick per server process. */
  seq?: number;
  /** Server wall clock (aware UTC ISO-8601) when the tick was assembled. */
  ts_ingest?: string;
  /** The twin's OWN simulated clock (same value as `timestamp`). Never event time. */
  sim_time?: string;
  sim_time_scale?: number;
  /** Nominal WALL seconds between payloads. */
  interval_s?: number;
  anomaly_status?: AnomalyStatusPayload;
}

export interface EquipmentHealthResponse {
  available: boolean;
  message?: string;
  trained_at_utc?: string;
  subset?: string;
  baseline?: { mae: number; rmse: number; r2: number };
  lstm?: { mae: number; rmse: number; r2: number };
  mae_improvement_pct?: number;
  beats_baseline?: boolean;
  dataset_caveat?: string;
}

export interface OptimizeSummary {
  mean_pue: number;
  mean_wue: number;
  mean_cooling_power_kw: number;
  total_water_consumed_L: number;
  total_reward: number;
  safety_violations: number;
}

export interface AnomalyScoreResponse {
  score: number;
  threshold: number;
  alert: boolean;
  type: string;
  message: string;
}

/** A row of GET /api/alerts. No rack/equipment id and no facility-state snapshot exist on it. */
export interface AlertRecord {
  id: number;
  created_at: string | null;
  type: string;
  message: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL' | string;
  score: number;
  alert: boolean;
  acknowledged: boolean;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  /** Alert identity/provenance (backend M2). null on alerts created before it. */
  origin?: string | null;
  model_version?: string | null;
  dedupe_key?: string | null;
}

/** GET /api/whatif response: an isolated 24h digital-twin run at constant inputs. */
export interface WhatIfResponse {
  hours: number;
  basis: string;
  mean_pue: number;
  wue: number;
  total_water_L: number;
  total_energy_kwh: number;
  total_co2_kg: number;
  max_outlet_temp_C: number;
  final_cooling_mode: string;
  drought_override_active: boolean;
  carbon_data_is_real: boolean;
  /** Echo of the request; absent on older backends. */
  inputs?: {
    utilisation: number;
    outside_temp_C: number;
    water_stress: number;
    mode: string;
    chilled_water_temp_C: number;
  };
}

export interface OptimizeResponse {
  results: StateResponse[];
  summary: OptimizeSummary;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
}

// ------------------------------------------------------------------ adapters (contract -> consumer shapes)
//
// This repo compiles with `strict: false`, where zod's inferred output types mark EVERY property optional. A
// plain `{ ...parsed }` therefore cannot satisfy the required fields above, so required fields are restated
// explicitly (no `as` casts). The values are already validated by the contract layer at this point.

/** An enum value as the backend sent it: known literals stay as they are, unrecognised ones keep their raw text. */
function rawValue(v: string | Unknown): string {
  return isUnknown(v) ? v.value : v;
}

export function toState(s: C.StateResponse): StateResponse {
  return {
    ...s,
    timestamp: s.timestamp,
    server_utilisation: s.server_utilisation,
    outside_temp_C: s.outside_temp_C,
    server_inlet_temp_C: s.server_inlet_temp_C,
    server_outlet_temp_C: s.server_outlet_temp_C,
    it_power_kw: s.it_power_kw,
    cooling_power_kw: s.cooling_power_kw,
    total_power_kw: s.total_power_kw,
    pue: s.pue,
    water_flow_lpm: s.water_flow_lpm,
    water_consumed_L: s.water_consumed_L,
    wue: s.wue,
    humidity_pct: s.humidity_pct,
    water_pressure_bar: s.water_pressure_bar,
    cooling_mode: rawValue(s.cooling_mode),
    anomaly: s.anomaly,
  };
}

function toAnomalyStatus(a: C.AnomalyStatusPayload): AnomalyStatusPayload {
  const { status, score, threshold, type, origin, episode, ...rest } = a;
  return {
    ...rest,
    status: rawValue(status),
    message: a.message,
    // Absent/null stays null (not scored); never 0.
    score: score ?? null,
    threshold: threshold ?? null,
    type: type ?? null,
    ...(origin !== undefined && { origin: origin === null ? null : rawValue(origin) }),
    ...(episode !== undefined && {
      episode: {
        ...episode,
        open: episode.open,
        dedupe_key: episode.dedupe_key ?? null,
        alert_id: episode.alert_id ?? null,
        start_seq: episode.start_seq ?? null,
        severity: episode.severity ?? null,
      },
    }),
  };
}

export function toLiveState(f: C.LiveFrame): LiveStatePayload {
  const { origin, anomaly_status, ...rest } = f;
  return {
    ...toState(rest),
    ...(origin !== undefined && { origin: rawValue(origin) }),
    ...(anomaly_status !== undefined && { anomaly_status: toAnomalyStatus(anomaly_status) }),
  };
}

export function toAlert(a: C.AlertRecord): AlertRecord {
  const { severity, origin, ...rest } = a;
  return {
    ...rest,
    id: a.id,
    created_at: a.created_at,
    type: a.type,
    message: a.message,
    severity: rawValue(severity),
    score: a.score,
    alert: a.alert,
    acknowledged: a.acknowledged,
    acknowledged_by: a.acknowledged_by,
    acknowledged_at: a.acknowledged_at,
    ...(origin !== undefined && { origin: origin === null ? null : rawValue(origin) }),
  };
}

export function toWhatIf(w: C.WhatIfResponse): WhatIfResponse {
  const { final_cooling_mode, inputs, ...rest } = w;
  return {
    ...rest,
    hours: w.hours,
    basis: w.basis,
    mean_pue: w.mean_pue,
    wue: w.wue,
    total_water_L: w.total_water_L,
    total_energy_kwh: w.total_energy_kwh,
    total_co2_kg: w.total_co2_kg,
    max_outlet_temp_C: w.max_outlet_temp_C,
    final_cooling_mode: rawValue(final_cooling_mode),
    drought_override_active: w.drought_override_active,
    carbon_data_is_real: w.carbon_data_is_real,
    ...(inputs !== undefined && {
      inputs: {
        ...inputs,
        utilisation: inputs.utilisation,
        outside_temp_C: inputs.outside_temp_C,
        water_stress: inputs.water_stress,
        mode: rawValue(inputs.mode),
        chilled_water_temp_C: inputs.chilled_water_temp_C,
      },
    }),
  };
}

export function toOptimize(o: C.OptimizeResult): OptimizeResponse {
  return {
    ...o,
    results: o.results.map(toState),
    summary: {
      ...o.summary,
      mean_pue: o.summary.mean_pue,
      mean_wue: o.summary.mean_wue,
      mean_cooling_power_kw: o.summary.mean_cooling_power_kw,
      total_water_consumed_L: o.summary.total_water_consumed_L,
      total_reward: o.summary.total_reward,
      safety_violations: o.summary.safety_violations,
    },
  };
}

export function toHealth(h: C.ApiHealth): HealthResponse {
  return { ...h, status: rawValue(h.status), timestamp: h.timestamp };
}

export function toEquipmentHealth(e: C.EquipmentHealth): EquipmentHealthResponse {
  const { baseline, lstm, ...rest } = e;
  return {
    ...rest,
    available: e.available,
    ...(baseline !== undefined && { baseline: { ...baseline, mae: baseline.mae, rmse: baseline.rmse, r2: baseline.r2 } }),
    ...(lstm !== undefined && { lstm: { ...lstm, mae: lstm.mae, rmse: lstm.rmse, r2: lstm.r2 } }),
  };
}

export function toAnomalyScore(d: { score: number; threshold: number; alert: boolean; type: string; message: string }): AnomalyScoreResponse {
  return { ...d, score: d.score, threshold: d.threshold, alert: d.alert, type: d.type, message: d.message };
}
