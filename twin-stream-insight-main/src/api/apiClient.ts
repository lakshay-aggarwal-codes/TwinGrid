/**
 * API client for the Digital Twin FastAPI backend (URL: VITE_API_BASE_URL, see src/config.ts).
 *
 * Every REST response passes the contract layer (`src/contract`) before it reaches a caller. Failures are
 * thrown as `ApiError` (client-chosen `safeMessage`; backend text goes only to `reportError`) or, when the
 * session is gone, `AuthRequiredError`. The WebSocket transport lives in `wsTransport.ts`.
 */
import { z } from 'zod';
import { reportError } from '@/lib/errorReporter.ts';
import { AuthRequiredError, forceRefresh, getToken } from '../authClient';
import { API_BASE_URL as BASE_URL, assertApiConfigured } from '../config';
import {
  AlertList,
  ApiHealth,
  EquipmentHealth,
  OptimizeResult,
  SimulateResponse,
  StateResponse as StateSchema,
  WhatIfResponse as WhatIfSchema,
  isSuccess,
  parseApi,
} from '../contract';
import { ApiError, describeBodyForReport, extractCode, kindForStatus, parseRetryAfter } from './apiError';
import {
  toAlert,
  toAnomalyScore,
  toEquipmentHealth,
  toHealth,
  toOptimize,
  toState,
  toWhatIf,
  type AlertRecord,
  type AnomalyScoreResponse,
  type EquipmentHealthResponse,
  type HealthResponse,
  type OptimizeResponse,
  type StateResponse,
  type WhatIfResponse,
} from './models.ts';

export { ApiError, isApiError, type ApiErrorKind } from './apiError';
export { connectWebSocket, probeHealthz } from './wsTransport.ts';
export type { BackendProbe, SocketStatus, TransportClosedReason, TransportState, TransportStatus, WsConnection } from './wsTransport.ts';
export type {
  AlertRecord,
  AnomalyPipelineStatus,
  AnomalyScoreResponse,
  AnomalyStatusPayload,
  EquipmentHealthResponse,
  HealthResponse,
  LiveStatePayload,
  OptimizeResponse,
  OptimizeSummary,
  StateResponse,
  WhatIfResponse,
} from './models.ts';

// ------------------------------------------------------------------ request plumbing

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

/** Path only: reports never carry a query string. */
function pathOf(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return '(unparsable url)';
  }
}

function isAbort(e: unknown): boolean {
  return typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError';
}

async function send(url: string, init: RequestInit, token: string): Promise<Response> {
  try {
    return await fetch(url, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
    });
  } catch (e) {
    if (isAbort(e)) throw e; // AbortSignal pass-through: the caller asked for it
    reportError('apiClient.network', `Request to ${pathOf(url)} failed`, 'warning');
    throw new ApiError({ kind: 'network' });
  }
}

async function accessToken(): Promise<string> {
  try {
    return await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError('apiClient.token', e, 'warning');
    throw new ApiError({ kind: 'unavailable' });
  }
}

/**
 * Attach the access token. On 401: refresh ONCE and retry ONCE; a second 401 is `AuthRequiredError`.
 * 403 is not an auth failure. Nothing else is retried, so a non-idempotent POST is never replayed after a
 * network failure or 5xx.
 */
async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  assertApiConfigured();
  let response = await send(url, init, await accessToken());
  if (response.status !== 401) return response;

  let fresh: string;
  try {
    fresh = await forceRefresh();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError('apiClient.refresh', e, 'warning');
    throw new ApiError({ kind: 'unavailable' });
  }
  response = await send(url, init, fresh);
  if (response.status === 401) throw new AuthRequiredError();
  return response;
}

async function readBody(response: Response, url: string): Promise<string> {
  try {
    return await response.text();
  } catch (e) {
    if (isAbort(e)) throw e;
    reportError('apiClient.network', `Reading response from ${pathOf(url)} failed`, 'warning');
    throw new ApiError({ kind: 'network', status: response.status });
  }
}

function parseJsonLoose(text: string): { ok: true; value: unknown } | { ok: false } {
  if (!text) return { ok: true, value: null };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

function errorFromResponse(response: Response, text: string, url: string): ApiError {
  const body = parseJsonLoose(text);
  const value = body.ok ? body.value : null;
  const kind = kindForStatus(response.status);
  // Raw detail is for the reporter only; it never reaches `safeMessage`.
  reportError(
    'apiClient.http',
    `${response.status} ${pathOf(url)}: ${describeBodyForReport(text, value)}`,
    kind === 'server' || kind === 'unavailable' ? 'error' : 'warning'
  );
  return new ApiError({
    kind,
    status: response.status,
    code: extractCode(value),
    retryAfterS: parseRetryAfter(response.headers?.get?.('Retry-After')),
  });
}

/** One validated REST call: authed fetch -> status mapping -> JSON -> contract schema -> consumer shape. */
async function callApi<S extends z.ZodTypeAny, R>(
  schema: S,
  context: string,
  url: string,
  init: RequestInit,
  adapt: (data: z.output<S>) => R
): Promise<R> {
  const response = await authedFetch(url, init);
  const text = await readBody(response, url);
  if (!response.ok) throw errorFromResponse(response, text, url);

  const body = parseJsonLoose(text);
  if (!body.ok) {
    // HTML error page or other non-JSON on a 2xx: never surfaced as raw text.
    reportError('apiClient.http', `${response.status} ${pathOf(url)}: body is not JSON`, 'error');
    throw new ApiError({ kind: 'server', status: response.status });
  }
  const parsed = parseApi(schema, body.value, context); // reports the violation (paths only)
  if (isSuccess(parsed)) return adapt(parsed.data);
  throw new ApiError({ kind: 'contract', status: response.status });
}

// ------------------------------------------------------------------ endpoints

/** GET /api/alerts — recent persisted alerts, newest first. */
export async function fetchAlerts(limit = 50, signal?: AbortSignal): Promise<AlertRecord[]> {
  return callApi(AlertList, 'GET /api/alerts', buildUrl('/api/alerts', { limit }), { signal }, (rows) => rows.map(toAlert));
}

export interface FetchStateParams {
  utilisation?: number;
  outside_temp?: number;
  water_stress?: number;
  mode?: string;
}

/** GET /api/state — current digital twin state. */
export async function fetchState(params: FetchStateParams = {}, signal?: AbortSignal): Promise<StateResponse> {
  const url = buildUrl('/api/state', {
    utilisation: params.utilisation,
    outside_temp: params.outside_temp,
    water_stress: params.water_stress,
    mode: params.mode,
  });
  return callApi(StateSchema, 'GET /api/state', url, { signal }, toState);
}

export interface FetchSimulationParams {
  utilisation?: number;
  outside_temp?: number;
  stress?: number;
}

/** GET /api/simulate/{hours} — hourly snapshots. */
export async function fetchSimulation(
  hours: number,
  params: FetchSimulationParams = {},
  signal?: AbortSignal
): Promise<StateResponse[]> {
  const url = buildUrl(`/api/simulate/${hours}`, {
    utilisation: params.utilisation,
    outside_temp: params.outside_temp,
    stress: params.stress,
  });
  return callApi(SimulateResponse, 'GET /api/simulate', url, { signal }, (rows) => rows.map(toState));
}

export interface WhatIfParams {
  utilisation: number;
  outside_temp: number;
  water_stress: number;
  mode: string;
  chilled_water_temp: number;
}

/** GET /api/whatif — real backend scenario result (never computed locally). */
export async function fetchWhatIf(params: WhatIfParams, signal?: AbortSignal): Promise<WhatIfResponse> {
  return callApi(WhatIfSchema, 'GET /api/whatif', buildUrl('/api/whatif', { ...params }), { signal }, toWhatIf);
}

export interface FetchOptimizedParams {
  alpha?: number;
  beta?: number;
  gamma?: number;
  water_stress?: number;
  hours?: number;
}

/** POST /api/optimize — optimized simulation results. Requires 'operator' role (viewer -> ApiError kind 'forbidden'). */
export async function fetchOptimized(weights: FetchOptimizedParams = {}, signal?: AbortSignal): Promise<OptimizeResponse> {
  return callApi(
    OptimizeResult,
    'POST /api/optimize',
    `${BASE_URL}/api/optimize`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        alpha: weights.alpha ?? 0.5,
        beta: weights.beta ?? 0.3,
        gamma: weights.gamma ?? 0.2,
        water_stress: weights.water_stress ?? 0,
        hours: weights.hours ?? 24,
      }),
    },
    toOptimize
  );
}

/** Local schema: the contract layer has none for this deprecated endpoint. */
const AnomalyScoreSchema = z
  .object({
    score: z.number().finite(),
    threshold: z.number().finite(),
    alert: z.boolean(),
    type: z.string(),
    message: z.string(),
  })
  .passthrough();

/**
 * @deprecated Anomaly scoring is server-owned (backend T3). Read `anomaly_status` from the live WebSocket
 * payload instead. The app no longer calls this.
 *
 * recentReadings must be exactly 12 tuples of
 * [water_flow_lpm, water_pressure_bar, server_outlet_temp_C, it_power_kw, humidity_pct], oldest first.
 */
export async function fetchAnomalyScore(
  recentReadings: [number, number, number, number, number][],
  signal?: AbortSignal
): Promise<AnomalyScoreResponse> {
  const url = buildUrl('/api/anomaly_score', { recent_data: JSON.stringify(recentReadings) });
  return callApi(AnomalyScoreSchema, 'GET /api/anomaly_score', url, { signal }, toAnomalyScore);
}

/**
 * GET /api/health (JWT). Proves the API answered, nothing more: it always says "healthy" when reachable and is
 * NOT a liveness probe (BC-15). Use `probeHealthz` for that.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return callApi(ApiHealth, 'GET /api/health', `${BASE_URL}/api/health`, { signal }, toHealth);
}

export { BASE_URL };

/** GET /api/equipment/health */
export async function fetchEquipmentHealth(signal?: AbortSignal): Promise<EquipmentHealthResponse> {
  return callApi(
    EquipmentHealth,
    'GET /api/equipment/health',
    `${BASE_URL}/api/equipment/health`,
    { signal },
    toEquipmentHealth
  );
}

// Type-only access to the validated contract layer. Consumers move onto these types in FE-03/05.
export type { ApiResult } from '../contract/parse';
export type * as Contract from '../contract';
