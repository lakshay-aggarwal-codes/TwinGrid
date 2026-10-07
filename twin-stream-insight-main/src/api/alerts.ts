/**
 * FE-12: alert lifecycle mutations. `POST /api/alerts/{id}/acknowledge` (BC-05, operator only).
 *
 * No optimistic success: the caller shows "pending", then refetches the list and shows the SERVER's row (`acknowledged_by`,
 * `acknowledged_at`). The response body is not interpreted -- the list is the source of truth -- so nothing from it can reach the UI.
 * 401 -> refresh once -> retry once (nothing was processed on a 401, so the replay is safe); everything else is surfaced as an
 * `ApiError` whose text is chosen by the client. 403 is final (authorisation in the UI is convenience only).
 */
import { AuthRequiredError, forceRefresh, getToken } from '../authClient';
import { API_BASE_URL, assertApiConfigured } from '../config';
import { reportError } from '@/lib/errorReporter';
import { ApiError, parseRetryAfter, type ApiErrorKind } from './apiError';

/** Status -> error kind (mirrors the REST client's mapping). */
function kindForAckStatus(status: number): ApiErrorKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status === 503) return 'unavailable';
  if (status >= 500) return 'server';
  return 'validation';
}

export const alertsQueryKey = (limit: number) => ['alerts', limit] as const;

export function acknowledgePath(id: number): string {
  return `/api/alerts/${encodeURIComponent(String(id))}/acknowledge`;
}

async function post(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { method: 'POST', signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError') throw e;
    reportError('alerts.network', 'Request to /api/alerts/{id}/acknowledge failed', 'warning');
    throw new ApiError({ kind: 'network' });
  }
}

export async function acknowledgeAlert(id: number, signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<void> {
  assertApiConfigured();
  const url = new URL(acknowledgePath(id), API_BASE_URL).toString();

  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError('alerts.token', e, 'warning');
    throw new ApiError({ kind: 'unavailable' });
  }

  let response = await post(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError('alerts.refresh', e, 'warning');
      throw new ApiError({ kind: 'unavailable' });
    }
    response = await post(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }

  if (!response.ok) {
    reportError('alerts.http', `${response.status} /api/alerts/{id}/acknowledge`, response.status >= 500 ? 'error' : 'warning');
    throw new ApiError({
      kind: kindForAckStatus(response.status),
      status: response.status,
      retryAfterS: parseRetryAfter(response.headers?.get?.('Retry-After')),
    });
  }
  // Drain and ignore the body: the refetched list is what the UI shows.
  try {
    await response.text();
  } catch {
    /* the acknowledgement itself succeeded */
  }
}
