/**
 * API client for the Digital Twin FastAPI backend (URL: VITE_API_BASE_URL, see src/config.ts).
 * All functions return parsed JSON and handle errors gracefully.
 *
 * All /api/* endpoints and /ws/live require a JWT -- see authClient.ts for
 * how that token is obtained (demo viewer account, no login screen).
 */

import { reportError } from '@/lib/errorReporter.ts';
import { getToken } from '../authClient';
import { API_BASE_URL as BASE_URL, WS_LIVE_URL as WS_BASE_URL, assertApiConfigured } from '../config';

const DEFAULT_RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 30000;

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

/**
 * One WebSocket /ws/live payload: the StateResponse fields plus the additive provenance/time fields
 * the backend gained in T1a. All of them are OPTIONAL because an older backend does not send them
 * (the UI then shows an "unverified source").
 */
/** Server-owned anomaly pipeline state (backend T3). The browser never scores anything itself. */
export type AnomalyPipelineStatus = 'warming_up' | 'ok' | 'anomalous' | 'unavailable' | 'error';

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
  /** Nominal simulated seconds per wall second. */
  sim_time_scale?: number;
  /** Nominal WALL seconds between payloads. */
  interval_s?: number;
  /** Server-side anomaly detection result. (The pre-existing `anomaly` number is the twin's own flag.) */
  anomaly_status?: AnomalyStatusPayload;
}

export type SocketStatus = 'connecting' | 'open' | 'closed';

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

/**
 * A single row from GET /api/alerts, exactly as api/routes/anomaly_routes.py's
 * list_alerts returns it -- see api/models/db_models.py's Alert table for the
 * backing schema. This is deliberately the FULL set of fields the backend
 * attaches to an alert: there is no rack/equipment ID and no facility-state
 * snapshot (Alert.sensor_reading_id exists in the schema but
 * data_repository.save_alert never sets it, so it's always null and the API
 * doesn't even expose it) -- don't assume either exists elsewhere in the app.
 */
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

/** GET /api/alerts — recent persisted alerts, newest first. */
export async function fetchAlerts(limit = 50): Promise<AlertRecord[]> {
  const url = buildUrl('/api/alerts', { limit });
  const response = await authedFetch(url);
  return handleResponse<AlertRecord[]>(response);
}

function buildUrl(path: string, params: Record<string, string | number | undefined> = {}): string {
  assertApiConfigured();
  const url = new URL(path, BASE_URL);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

async function handleResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(text || `Request failed: ${response.status} ${response.statusText}`);
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    const message = typeof detail === 'string' ? detail : response.statusText || JSON.stringify(detail);
    const err = new Error(message) as Error & { status?: number; data?: unknown };
    err.status = response.status;
    err.data = data;
    throw err;
  }
  return data as T;
}

async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  assertApiConfigured();
  const token = await getToken();
  return fetch(url, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

export interface FetchStateParams {
  utilisation?: number;
  outside_temp?: number;
  water_stress?: number;
  mode?: string;
}

/** GET /api/state — current digital twin state. */
export async function fetchState(params: FetchStateParams = {}): Promise<StateResponse> {
  const url = buildUrl('/api/state', {
    utilisation: params.utilisation,
    outside_temp: params.outside_temp,
    water_stress: params.water_stress,
    mode: params.mode,
  });
  const response = await authedFetch(url);
  return handleResponse<StateResponse>(response);
}

export interface FetchSimulationParams {
  utilisation?: number;
  outside_temp?: number;
  stress?: number;
}

/** GET /api/simulate/{hours} — hourly snapshots. */
export async function fetchSimulation(
  hours: number,
  params: FetchSimulationParams = {}
): Promise<StateResponse[]> {
  const url = buildUrl(`/api/simulate/${hours}`, {
    utilisation: params.utilisation,
    outside_temp: params.outside_temp,
    stress: params.stress,
  });
  const response = await authedFetch(url);
  return handleResponse<StateResponse[]>(response);
}

export interface WhatIfParams {
  utilisation: number;
  outside_temp: number;
  water_stress: number;
  mode: string;
  chilled_water_temp: number;
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
}

/** GET /api/whatif — real backend scenario result (never computed locally). */
export async function fetchWhatIf(params: WhatIfParams, signal?: AbortSignal): Promise<WhatIfResponse> {
  const url = buildUrl('/api/whatif', { ...params });
  const response = await authedFetch(url, { signal });
  return handleResponse<WhatIfResponse>(response);
}

export interface FetchOptimizedParams {
  alpha?: number;
  beta?: number;
  gamma?: number;
  water_stress?: number;
  hours?: number;
}

/** POST /api/optimize — optimized simulation results. Requires 'operator' role. */
export async function fetchOptimized(weights: FetchOptimizedParams = {}): Promise<{
  results: StateResponse[];
  summary: OptimizeSummary;
}> {
  const response = await authedFetch(`${BASE_URL}/api/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      alpha: weights.alpha ?? 0.5,
      beta: weights.beta ?? 0.3,
      gamma: weights.gamma ?? 0.2,
      water_stress: weights.water_stress ?? 0,
      hours: weights.hours ?? 24,
    }),
  });
  return handleResponse(response);
}

/**
 * @deprecated Anomaly scoring is server-owned (backend T3). Read `anomaly_status` from the live
 * WebSocket payload instead. This calls a pure, deprecated compatibility endpoint that scores a
 * caller-supplied window and creates no alerts; the app no longer calls it.
 *
 * recentReadings must be exactly 12 tuples of
 * [water_flow_lpm, water_pressure_bar, server_outlet_temp_C, it_power_kw, humidity_pct],
 * oldest first.
 */
export async function fetchAnomalyScore(
  recentReadings: [number, number, number, number, number][]
): Promise<AnomalyScoreResponse> {
  const url = buildUrl('/api/anomaly_score', { recent_data: JSON.stringify(recentReadings) });
  const response = await authedFetch(url);
  return handleResponse<AnomalyScoreResponse>(response);
}

/**
 * WebSocket /ws/live — live state updates, auto-reconnect, auto re-auth.
 * `onStatus` (optional) reports the socket state so the UI can tell "connected" from "dropped".
 */
export function connectWebSocket(
  onMessage: (state: LiveStatePayload) => void,
  onStatus?: (status: SocketStatus) => void
): { disconnect: () => void } {
  let ws: WebSocket | null = null;
  let reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  async function connect() {
    if (closed) return;
    onStatus?.('connecting');
    let token: string;
    try {
      token = await getToken();
    } catch (e) {
      reportError('apiClient.websocket.auth', e, 'warning');
      onStatus?.('closed');
      scheduleReconnect();
      return;
    }
    if (closed) return;

    try {
      ws = new WebSocket(`${WS_BASE_URL}?token=${encodeURIComponent(token)}`);
    } catch {
      onStatus?.('closed');
      scheduleReconnect();
      return;
    }

    ws.onmessage = (event) => {
      try {
        const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        onMessage(data as LiveStatePayload);
      } catch (e) {
        reportError('apiClient.websocket.parse', e, 'warning');
      }
    };

    ws.onclose = (event) => {
      ws = null;
      if (closed) return;
      onStatus?.('closed');
      // Previously silent. The header's Live/Connecting indicator shows this to
      // an operator watching; this makes it visible to anyone who isn't.
      reportError('apiClient.websocket.closed', `WebSocket closed (code ${event.code}); reconnecting`, 'warning');
      scheduleReconnect();
    };

    // The browser gives no detail on WebSocket errors (a close event always
    // follows and is what gets reported), so nothing more to add here.
    ws.onerror = () => {};

    ws.onopen = () => {
      reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
      onStatus?.('open');
    };
  }

  function scheduleReconnect() {
    if (closed || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
      reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY_MS);
    }, reconnectDelay);
  }

  connect();

  return {
    disconnect() {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (ws) {
        ws.close();
        ws = null;
      }
    },
  };
}

/** GET /api/health */
export async function fetchHealth(): Promise<{ status: string; timestamp: string }> {
  const response = await authedFetch(`${BASE_URL}/api/health`);
  return handleResponse(response);
}

export { BASE_URL };

/** GET /api/equipment/health */
export async function fetchEquipmentHealth(): Promise<EquipmentHealthResponse> {
  const response = await authedFetch(`${BASE_URL}/api/equipment/health`);
  return handleResponse(response);
}

// FE-01: type-only access to the validated contract layer. No runtime change; the existing interfaces above
// are replaced by contract types in FE-02.
export type { ApiResult } from '../contract/parse';
export type * as Contract from '../contract';
