/**
 * FE-14: read-only fetch of the backend-authored topology (BC-08): `GET /api/facility` + `GET /api/assets` (paginated).
 *
 * Live topology only: `as_of` is not sent and `include_unplaced` is not requested. Responses pass the contract layer
 * (`Facility`, `AssetsResponse`); failures are `ApiError`s with client-chosen text. 401 -> refresh once -> retry once.
 */
import { AuthRequiredError, forceRefresh, getToken } from '../authClient';
import { API_BASE_URL, assertApiConfigured } from '../config';
import { reportError } from '@/lib/errorReporter';
import { Facility, AssetsResponse, type Asset } from '@/contract/schemas/facility';
import { isSuccess, parseApi } from '@/contract/parse';
import { ApiError, parseRetryAfter, type ApiErrorKind } from './apiError';

export const ASSETS_PAGE_SIZE = 1000; // backend maximum (`limit` <= 1000)
const MAX_PAGES = 5;

export interface FacilityTopologyRaw {
  readonly facility: Facility;
  /** `frame_unit` echoed by /api/assets (must agree with the facility's). */
  readonly assetsFrameUnit: string;
  readonly assets: readonly Asset[];
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status === 503) return 'unavailable';
  if (status >= 500) return 'server';
  return 'validation';
}

async function send(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError') throw e;
    reportError('facility.network', 'Request to the facility endpoints failed', 'warning');
    throw new ApiError({ kind: 'network' });
  }
}

async function getJson(path: string, params: Record<string, string | number>, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<unknown> {
  assertApiConfigured();
  const u = new URL(path, API_BASE_URL);
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, String(v));
  const url = u.toString();

  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError('facility.token', e, 'warning');
    throw new ApiError({ kind: 'unavailable' });
  }
  let response = await send(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError('facility.refresh', e, 'warning');
      throw new ApiError({ kind: 'unavailable' });
    }
    response = await send(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError('facility.http', `${response.status} ${path}`, response.status >= 500 ? 'error' : 'warning');
    throw new ApiError({ kind: kindForStatus(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.('Retry-After')) });
  }
  try {
    return JSON.parse(await response.text());
  } catch {
    reportError('facility.http', `${response.status} ${path}: body is not JSON`, 'error');
    throw new ApiError({ kind: 'server', status: response.status });
  }
}

export async function fetchFacilityTopology(signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<FacilityTopologyRaw> {
  const fBody = await getJson('/api/facility', {}, signal, fetchImpl);
  const f = parseApi(Facility, fBody, 'GET /api/facility');
  if (!isSuccess(f)) throw new ApiError({ kind: 'contract' });

  const assets: Asset[] = [];
  let assetsFrameUnit = '';
  for (let page = 0; page < MAX_PAGES; page++) {
    const body = await getJson('/api/assets', { limit: ASSETS_PAGE_SIZE, offset: page * ASSETS_PAGE_SIZE }, signal, fetchImpl);
    const parsed = parseApi(AssetsResponse, body, 'GET /api/assets');
    if (!isSuccess(parsed)) throw new ApiError({ kind: 'contract' });
    assetsFrameUnit = parsed.data.frame_unit;
    assets.push(...parsed.data.assets);
    if (parsed.data.assets.length < ASSETS_PAGE_SIZE) break;
  }
  return { facility: f.data, assetsFrameUnit, assets };
}
