/**
 * FE-02: typed REST/transport error.
 *
 * `safeMessage` (and therefore `Error.message`) is chosen by the CLIENT from `kind`; backend `detail`/body
 * text is never copied into it. The raw detail goes only to `reportError` (see `apiClient.ts`).
 */

export type ApiErrorKind =
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'validation'
  | 'unavailable'
  | 'server'
  | 'network'
  | 'contract';

const SAFE_MESSAGES: Record<ApiErrorKind, string> = {
  unauthenticated: 'Your session has ended. Please sign in again.',
  forbidden: 'You do not have permission to do that.',
  not_found: 'The requested item was not found.',
  conflict: 'The request conflicts with the current state.',
  rate_limited: 'Too many requests. Try again shortly.',
  validation: 'The request was not accepted. Check the inputs and try again.',
  unavailable: 'The service is unavailable. Try again later.',
  server: 'The server could not complete the request.',
  network: 'Could not reach the server. Check your connection.',
  contract: 'The server sent a response this app cannot use.',
};

export function safeMessageFor(kind: ApiErrorKind): string {
  return SAFE_MESSAGES[kind];
}

export interface ApiErrorInit {
  kind: ApiErrorKind;
  status?: number;
  /** Machine code from a structured error body (BC-13). Only accepted when it looks like a code. */
  code?: string;
  retryAfterS?: number;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;
  readonly safeMessage: string;
  readonly retryAfterS?: number;

  constructor(init: ApiErrorInit) {
    const safeMessage = SAFE_MESSAGES[init.kind];
    super(safeMessage);
    this.name = 'ApiError';
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code;
    this.safeMessage = safeMessage;
    this.retryAfterS = init.retryAfterS;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Interim status -> kind mapper (BC-13 structured errors do not exist yet). */
export function kindForStatus(status: number): ApiErrorKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status === 502 || status === 503 || status === 504) return 'unavailable';
  if (status >= 500) return 'server';
  return 'validation'; // other 4xx (400, 422, ...)
}

const CODE_RE = /^[A-Za-z0-9_.-]{1,64}$/;

/** A machine code from the body (`code`, or `detail.code`), only if it is a short identifier-like string. */
const PROBLEM_TYPE_RE = /^urn:twingrid:error:([A-Za-z0-9_.-]{1,64})$/;

export function extractCode(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const direct = (body as { code?: unknown }).code;
  const nested = (body as { detail?: { code?: unknown } | unknown }).detail;
  const candidate = typeof direct === 'string' ? direct : (nested as { code?: unknown } | null)?.code;
  if (typeof candidate === 'string' && CODE_RE.test(candidate)) return candidate;
  // The backend's problem+json body carries its machine code as the suffix of `type` (api/errors.py).
  const type = (body as { type?: unknown }).type;
  const m = typeof type === 'string' ? PROBLEM_TYPE_RE.exec(type) : null;
  return m ? m[1] : undefined;
}

/** Delta-seconds form of Retry-After only (the backend sends integers); HTTP-dates are ignored. */
export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (!value || !/^\d{1,6}$/.test(value.trim())) return undefined;
  return Number(value.trim());
}

/** Bounded, single-line text for the error reporter. Never shown to users. */
export function describeBodyForReport(text: string, body: unknown): string {
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined;
  const raw = typeof detail === 'string' ? detail : text;
  return raw.replace(/\s+/g, ' ').slice(0, 200);
}
