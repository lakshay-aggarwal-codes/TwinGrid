/**
 * API client for Digital Twin FastAPI backend.
 * All functions return parsed JSON and handle errors gracefully.
 */

const BASE_URL = 'https://function-bun-production-6ce5.up.railway.app';
const WS_URL = 'wss://function-bun-production-6ce5.up.railway.app/ws/live';

const DEFAULT_RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 30000;

/**
 * Build URL with optional query params.
 * @param {string} path - API path (e.g. '/api/state')
 * @param {Record<string, string | number | undefined>} [params] - Query params
 * @returns {string}
 */
function buildUrl(path, params = {}) {
  const url = new URL(path, BASE_URL);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

/**
 * Handle response: parse JSON or throw with message.
 * @param {Response} response
 * @returns {Promise<unknown>}
 */
async function handleResponse(response) {
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(text || `Request failed: ${response.status} ${response.statusText}`);
  }
  if (!response.ok) {
    const message = data?.detail || data?.message || response.statusText || String(data);
    const err = new Error(typeof message === 'string' ? message : JSON.stringify(message));
    err.status = response.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * Fetch current digital twin state.
 * @param {{
 *   utilisation?: number;
 *   outside_temp?: number;
 *   water_stress?: number;
 *   mode?: string;
 * }} [params] - utilisation (0-1), outside_temp (°C), water_stress (0-1), mode (auto|free_air|closed_loop|evaporative|hybrid)
 * @returns {Promise<Record<string, unknown>>} State object
 */
export async function fetchState(params = {}) {
  const url = buildUrl('/api/state', {
    utilisation: params.utilisation,
    outside_temp: params.outside_temp,
    water_stress: params.water_stress,
    mode: params.mode,
  });
  const response = await fetch(url);
  return handleResponse(response);
}

/**
 * Fetch simulation results for a given number of hours.
 * @param {number} hours - Hours to simulate (1–168)
 * @param {{
 *   utilisation?: number;
 *   stress?: number;
 * }} [params] - utilisation (0-1), stress / water_stress (0-1)
 * @returns {Promise<Array<Record<string, unknown>>>} Array of hourly state snapshots
 */
export async function fetchSimulation(hours, params = {}) {
  const url = buildUrl(`/api/simulate/${hours}`, {
    utilisation: params.utilisation,
    stress: params.stress,
  });
  const response = await fetch(url);
  return handleResponse(response);
}

/**
 * Run RL optimization and return results.
 * @param {{
 *   alpha?: number;
 *   beta?: number;
 *   gamma?: number;
 *   water_stress?: number;
 *   hours?: number;
 * }} weights - alpha, beta, gamma (0-1), water_stress (0-1), hours (1-168)
 * @returns {Promise<{ results: Array<unknown>; summary: Record<string, number> }>} Optimized simulation results and summary
 */
export async function fetchOptimized(weights = {}) {
  const body = {
    alpha: weights.alpha ?? 0.5,
    beta: weights.beta ?? 0.3,
    gamma: weights.gamma ?? 0.2,
    water_stress: weights.water_stress ?? 0,
    hours: weights.hours ?? 24,
  };
  const response = await fetch(`${BASE_URL}/api/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

/**
 * Connect to live WebSocket and call onMessage for each new state.
 * Auto-reconnects on disconnect with backoff.
 * @param {(state: Record<string, unknown>) => void} onMessage - Callback for each state update
 * @returns {{ disconnect: () => void }} Object with disconnect() to stop reconnecting and close socket
 */
export function connectWebSocket(onMessage) {
  let ws = null;
  let reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
  let reconnectTimer = null;
  let closed = false;

  function connect() {
    if (closed) return;
    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      scheduleReconnect();
      return;
    }

    ws.onmessage = (event) => {
      try {
        const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        onMessage(data);
      } catch (e) {
        console.warn('[api_client] WebSocket message parse error:', e);
      }
    };

    ws.onclose = () => {
      ws = null;
      if (!closed) scheduleReconnect();
    };

    ws.onerror = () => {
      // Connection will trigger onclose
    };

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

/**
 * Health check.
 * @returns {Promise<{ status: string; timestamp: string }>}
 */
export async function fetchHealth() {
  const response = await fetch(`${BASE_URL}/api/health`);
  return handleResponse(response);
}

export { BASE_URL, WS_URL };
