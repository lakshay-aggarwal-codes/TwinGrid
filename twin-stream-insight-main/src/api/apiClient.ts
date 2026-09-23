/**
 * API client for Digital Twin FastAPI backend (https://function-bun-production-6ce5.up.railway.app).
 * All functions return parsed JSON and handle errors gracefully.
 *
 * All /api/* endpoints and /ws/live require a JWT -- see authClient.ts for
 * how that token is obtained (demo viewer account, no login screen).
 */

import { getToken } from '../authClient';

const BASE_URL = 'https://function-bun-production-6ce5.up.railway.app';
const WS_BASE_URL = 'wss://function-bun-production-6ce5.up.railway.app/ws/live';

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

function buildUrl(path: string, params: Record<string, string | number | undefined> = {}): string {
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
  stress?: number;
}

/** GET /api/simulate/{hours} — hourly snapshots. */
export async function fetchSimulation(
  hours: number,
  params: FetchSimulationParams = {}
): Promise<StateResponse[]> {
  const url = buildUrl(`/api/simulate/${hours}`, {
    utilisation: params.utilisation,
    stress: params.stress,
  });
  const response = await authedFetch(url);
  return handleResponse<StateResponse[]>(response);
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
 * GET /api/anomaly_score — score the last 12 readings.
 * recentReadings must be exactly 12 tuples of
 * [water_flow_lpm, water_pressure_bar, server_outlet_temp_C, it_power_kw, humidity_pct],
 * oldest first, matching the shape the trained LSTM autoencoder expects.
 */
export async function fetchAnomalyScore(
  recentReadings: [number, number, number, number, number][]
): Promise<AnomalyScoreResponse> {
  const url = buildUrl('/api/anomaly_score', { recent_data: JSON.stringify(recentReadings) });
  const response = await authedFetch(url);
  return handleResponse<AnomalyScoreResponse>(response);
}

/** WebSocket /ws/live — live state updates, auto-reconnect, auto re-auth. */
export function connectWebSocket(onMessage: (state: StateResponse) => void): { disconnect: () => void } {
  let ws: WebSocket | null = null;
  let reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  async function connect() {
    if (closed) return;
    let token: string;
    try {
      token = await getToken();
    } catch (e) {
      console.warn('[apiClient] WebSocket auth failed, will retry:', e);
      scheduleReconnect();
      return;
    }
    if (closed) return;

    try {
      ws = new WebSocket(`${WS_BASE_URL}?token=${encodeURIComponent(token)}`);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onmessage = (event) => {
      try {
        const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        onMessage(data as StateResponse);
      } catch (e) {
        console.warn('[apiClient] WebSocket parse error:', e);
      }
    };

    ws.onclose = () => {
      ws = null;
      if (!closed) scheduleReconnect();
    };

    ws.onerror = () => {};

    ws.onopen = () => {
      reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
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