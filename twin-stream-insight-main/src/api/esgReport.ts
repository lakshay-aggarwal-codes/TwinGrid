/**
 * FE-10: authenticated download of the backend-generated ESG report PDF (`GET /api/esg_report`, BC-16).
 *
 * A plain link cannot carry the bearer token, so the PDF is fetched as a blob with the same 401 -> refresh once -> retry once
 * behaviour as every other REST call. The PDF is saved as received: it is NOT edited, so any provenance the backend put inside it
 * is the backend's own (backend provenance inside the PDF is [MR], not yet implemented).
 *
 * Failures are `ApiError`s with client-chosen messages; backend body text never reaches the user.
 */
import { AuthRequiredError, forceRefresh, getToken } from '../authClient';
import { API_BASE_URL, assertApiConfigured } from '../config';
import { reportError } from '@/lib/errorReporter';
import { ApiError, type ApiErrorKind } from './apiError';

export const ESG_REPORT_PATH = '/api/esg_report';
export const ESG_REPORT_FILENAME = 'twingrid-esg-report.pdf';

export interface EsgReportFile {
  readonly blob: Blob;
  readonly filename: string;
}

/** Status -> error kind (mirrors the REST client's mapping). */
export function esgErrorKind(status: number): ApiErrorKind {
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
    return await fetchImpl(url, { signal, headers: { Authorization: `Bearer ${token}`, Accept: 'application/pdf' } });
  } catch (e) {
    if (typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError') throw e;
    reportError('esgReport.network', `Request to ${ESG_REPORT_PATH} failed`, 'warning');
    throw new ApiError({ kind: 'network' });
  }
}

async function token(): Promise<string> {
  try {
    return await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError('esgReport.token', e, 'warning');
    throw new ApiError({ kind: 'unavailable' });
  }
}

export async function fetchEsgReportPdf(signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<EsgReportFile> {
  assertApiConfigured();
  const url = new URL(ESG_REPORT_PATH, API_BASE_URL).toString();

  let response = await send(url, await token(), signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError('esgReport.refresh', e, 'warning');
      throw new ApiError({ kind: 'unavailable' });
    }
    response = await send(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }

  if (!response.ok) {
    reportError('esgReport.http', `${response.status} ${ESG_REPORT_PATH}`, response.status >= 500 ? 'error' : 'warning');
    throw new ApiError({ kind: esgErrorKind(response.status), status: response.status });
  }

  const type = response.headers?.get?.('Content-Type') ?? '';
  if (!/application\/pdf/i.test(type)) {
    // A 2xx that is not a PDF (an HTML error page, a proxy login page): never offered as a download.
    reportError('esgReport.http', `${response.status} ${ESG_REPORT_PATH}: unexpected content type`, 'error');
    throw new ApiError({ kind: 'server', status: response.status });
  }

  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    reportError('esgReport.network', `Reading ${ESG_REPORT_PATH} failed`, 'warning');
    throw new ApiError({ kind: 'network' });
  }
  return { blob: new Blob([blob], { type: 'application/pdf' }), filename: ESG_REPORT_FILENAME };
}
