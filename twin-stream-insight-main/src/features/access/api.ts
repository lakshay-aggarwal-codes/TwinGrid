/**
 * Typed client for the §8.1 access-request endpoints. Every function resolves (never throws) to a tagged result so
 * the UI handles each outcome explicitly. Bodies are validated at runtime; a body that is not the documented shape
 * is "unexpected", not repaired. No function sends or stores anything but what the contract lists.
 */
import { API_BASE_URL, assertApiConfigured } from '@/config.ts';
import { isFailure, parseApi } from '@/contract';
import {
  AccessRequestCreated,
  AccessRequestStatus,
  ActivateOk,
  ResendAck,
} from './schemas';

export type { AccessRequestCreated, AccessRequestStatus, AccessStatus } from './schemas';

export type Failure = 'offline' | 'rate_limited' | 'unexpected';

export type SubmitResult =
  | { kind: 'ok'; data: AccessRequestCreated }
  | { kind: 'invalid' }
  | { kind: Failure };

export type StatusResult =
  | { kind: 'ok'; data: AccessRequestStatus }
  | { kind: 'not_found' }
  | { kind: Failure };

export type ResendResult = { kind: 'ok' } | { kind: 'not_found' } | { kind: Failure };

export type ActivateResult =
  | { kind: 'ok' }
  | { kind: 'invalid_or_expired' }
  | { kind: 'invalid' }
  | { kind: Failure };

const BASE = '/api/access-requests';

async function send(
  path: string,
  init: { method: 'GET' | 'POST'; body?: unknown; headers?: Record<string, string> },
): Promise<{ status: number; body: unknown } | 'offline'> {
  try {
    assertApiConfigured();
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: init.method,
      headers: { ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { status: response.status, body };
  } catch {
    return 'offline';
  }
}

export async function submitAccessRequest(input: { name: string; email: string; purpose: string }): Promise<SubmitResult> {
  const res = await send(BASE, {
    method: 'POST',
    body: { name: input.name.trim(), email: input.email.trim(), purpose: input.purpose.trim() },
  });
  if (res === 'offline') return { kind: 'offline' };
  if (res.status === 422) return { kind: 'invalid' };
  if (res.status === 429) return { kind: 'rate_limited' };
  if (res.status !== 202) return { kind: 'unexpected' };
  const parsed = parseApi(AccessRequestCreated, res.body, 'POST /api/access-requests');
  return isFailure(parsed) ? { kind: 'unexpected' } : { kind: 'ok', data: parsed.data };
}

export async function fetchRequestStatus(ref: string, token: string): Promise<StatusResult> {
  const res = await send(`${BASE}/${encodeURIComponent(ref)}/status`, { method: 'GET', headers: { 'X-Request-Token': token } });
  if (res === 'offline') return { kind: 'offline' };
  if (res.status === 404) return { kind: 'not_found' };
  if (res.status === 429) return { kind: 'rate_limited' };
  if (res.status !== 200) return { kind: 'unexpected' };
  const parsed = parseApi(AccessRequestStatus, res.body, 'GET /api/access-requests/{ref}/status');
  return isFailure(parsed) ? { kind: 'unexpected' } : { kind: 'ok', data: parsed.data };
}

export async function resendActivation(ref: string, token: string): Promise<ResendResult> {
  const res = await send(`${BASE}/resend-activation`, { method: 'POST', body: { ref, status_token: token } });
  if (res === 'offline') return { kind: 'offline' };
  if (res.status === 404) return { kind: 'not_found' };
  if (res.status === 429) return { kind: 'rate_limited' };
  if (res.status !== 202) return { kind: 'unexpected' };
  const parsed = parseApi(ResendAck, res.body, 'POST /api/access-requests/resend-activation');
  return isFailure(parsed) ? { kind: 'unexpected' } : { kind: 'ok' };
}

/** The password is sent once, in the body, and is never logged or stored by this client. */
export async function activateAccount(token: string, password: string): Promise<ActivateResult> {
  const res = await send(`${BASE}/activate`, { method: 'POST', body: { token, password } });
  if (res === 'offline') return { kind: 'offline' };
  if (res.status === 400) return { kind: 'invalid_or_expired' };
  if (res.status === 422) return { kind: 'invalid' };
  if (res.status === 429) return { kind: 'rate_limited' };
  if (res.status !== 200) return { kind: 'unexpected' };
  const parsed = parseApi(ActivateOk, res.body, 'POST /api/access-requests/activate');
  return isFailure(parsed) ? { kind: 'unexpected' } : { kind: 'ok' };
}

/** Pure; exported for tests and for the form's inline validation (mirrors the server's documented limits). */
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;
