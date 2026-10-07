/**
 * Real sign-in for the dashboard: login -> short-lived access token (kept in
 * memory only) + rotating refresh token -> silent refresh -> logout.
 *
 * - The ACCESS token never touches storage. It lives in this module's memory and
 *   is re-obtained from the refresh token after a page reload.
 * - The REFRESH token is kept in sessionStorage (this tab only, gone when the tab
 *   closes) so a reload does not force a new sign-in. That is a deliberate
 *   trade-off: any script running on the page can read it. Set
 *   PERSIST_REFRESH_TOKEN to false to make sign-in survive nothing but this
 *   page's lifetime.
 * - Refresh tokens are single-use on the server (rotation + reuse detection), so
 *   concurrent refreshes MUST share one request: two requests with the same token
 *   would look like token theft and revoke the whole session.
 * - There are NO baked credentials. The only exception is a DEV-ONLY convenience:
 *   `import.meta.env.DEV` is false in a production build, so the bundler removes
 *   the whole branch (and the VITE_DEMO_* values with it); this is asserted by
 *   src/test/bundleScan.test.ts, which builds for production and greps the output.
 */

import { API_BASE_URL, assertApiConfigured } from './config.ts';
import { TokenResponse, isUnknown, isFailure, parseApi } from './contract';

/** Roles this client knows. The backend's vocabulary is authoritative: any other value is kept as-is (see AuthRole). */
export type Role = 'viewer' | 'operator';
/**
 * The role as the backend stated it. A value this client does not recognise stays that string and is treated as
 * "not operator" for UX purposes. A role is a display/gating HINT only: the server decides what a request may do (403 is final).
 */
export type AuthRole = Role | (string & {});

/** Shown on the sign-in screen when the session ended without the user asking for it (expired, revoked, rejected). */
export const SESSION_ENDED_NOTICE = 'Session ended — sign in again';
export type AuthStatus = 'restoring' | 'signed-out' | 'signed-in';

export interface AuthSnapshot {
  status: AuthStatus;
  username: string | null;
  role: AuthRole | null;
  /** Why the user is signed out, when it was not their own doing (e.g. server unreachable on reload). */
  notice: string | null;
}

/** Thrown when there is no usable session. The UI reacts by showing the sign-in screen. */
export class AuthRequiredError extends Error {
  constructor(message = 'Sign-in required') {
    super(message);
    this.name = 'AuthRequiredError';
  }
}

/** Sign-in failed. `message` is safe to show to the user. */
export class LoginError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = 'LoginError';
    this.status = status;
  }
}

const PERSIST_REFRESH_TOKEN = true;
const STORAGE_KEY = 'twingrid.session';
/** Refresh the access token when less than this is left on it. */
const REFRESH_MARGIN_MS = 60_000;

// DEV-ONLY demo account. In a production build `import.meta.env.DEV` is the
// literal `false`, this folds to `null`, and the VITE_DEMO_* reads are dropped.
const DEV_DEMO: { username: string; password: string } | null =
  import.meta.env.DEV && import.meta.env.VITE_DEMO_USERNAME && import.meta.env.VITE_DEMO_PASSWORD
    ? {
        username: import.meta.env.VITE_DEMO_USERNAME as string,
        password: import.meta.env.VITE_DEMO_PASSWORD as string,
      }
    : null;

/** The validated /auth/login and /auth/refresh body (contract layer); `role` is the raw backend string. */
interface Tokens {
  access_token: string;
  refresh_token: string;
  role: AuthRole;
}

interface Internal {
  accessToken: string | null;
  expiresAtMs: number;
  refreshToken: string | null;
  username: string | null;
  role: AuthRole | null;
}

const EMPTY: Internal = { accessToken: null, expiresAtMs: 0, refreshToken: null, username: null, role: null };

let internal: Internal = { ...EMPTY };
let status: AuthStatus = 'signed-out';
let notice: string | null = null;
let snapshot: AuthSnapshot = { status, username: null, role: null, notice: null };
/** Bumped by every sign-out so a response that arrives late cannot resurrect a dead session. */
let generation = 0;
let refreshInFlight: Promise<string> | null = null;
let initPromise: Promise<void> | null = null;
let devDemoDisabled = false;
const listeners = new Set<() => void>();

// ------------------------------------------------------------------ store plumbing (useSyncExternalStore)
function publish(): void {
  snapshot = { status, username: internal.username, role: internal.role, notice };
  listeners.forEach((l) => l());
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAuthSnapshot(): AuthSnapshot {
  return snapshot;
}

// ------------------------------------------------------------------ storage
function readStored(): { refreshToken: string; username: string } | null {
  if (!PERSIST_REFRESH_TOKEN) return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { refreshToken?: unknown; username?: unknown };
    if (typeof parsed.refreshToken === 'string' && typeof parsed.username === 'string') {
      return { refreshToken: parsed.refreshToken, username: parsed.username };
    }
  } catch {
    // unreadable storage or corrupt value: behave as signed out
  }
  return null;
}

function writeStored(): void {
  if (!PERSIST_REFRESH_TOKEN) return;
  try {
    if (internal.refreshToken && internal.username) {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ refreshToken: internal.refreshToken, username: internal.username })
      );
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // storage unavailable (private mode / quota): the session just won't survive a reload
  }
}

// ------------------------------------------------------------------ session state transitions
function decodeExpiryMs(token: string): number {
  try {
    // JWTs are base64url ("-" and "_"); atob() only understands plain base64.
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(b64));
    if (typeof payload.exp === 'number') return payload.exp * 1000;
  } catch {
    // fall through
  }
  // Unreadable token: assume a short life so we refresh soon rather than trust it.
  return Date.now() + 2 * REFRESH_MARGIN_MS;
}

function applyTokens(data: Tokens, username: string, forGeneration: number): void {
  if (forGeneration !== generation) return; // signed out while the request was in flight
  internal = {
    accessToken: data.access_token,
    expiresAtMs: decodeExpiryMs(data.access_token),
    refreshToken: data.refresh_token,
    username,
    role: data.role,
  };
  status = 'signed-in';
  notice = null;
  writeStored();
  publish();
}

function clearSession(message: string | null = null, keepStored = false): void {
  generation += 1;
  internal = { ...EMPTY };
  status = 'signed-out';
  notice = message;
  if (!keepStored) writeStored();
  publish();
}

// ------------------------------------------------------------------ requests
async function postJson(path: string, body: unknown): Promise<Response> {
  assertApiConfigured();
  return fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** Validate a token response through the contract layer. Returns null when it is not the documented shape. */
async function readTokens(response: Response, context: string): Promise<Tokens | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  const parsed = parseApi(TokenResponse, body, context);
  if (isFailure(parsed)) return null;
  const { access_token, refresh_token, role } = parsed.data;
  return { access_token, refresh_token, role: isUnknown(role) ? role.value : role };
}

/** Sign in with a username and password. Throws LoginError (message is user-safe). */
export async function login(username: string, password: string): Promise<void> {
  const name = username.trim();
  let response: Response;
  try {
    response = await postJson('/auth/login', { username: name, password });
  } catch {
    throw new LoginError('Could not reach the server. Check your connection and try again.');
  }
  if (response.status === 401) throw new LoginError('Invalid username or password.', 401);
  if (response.status === 429) throw new LoginError('Too many sign-in attempts. Wait a minute and try again.', 429);
  if (!response.ok) throw new LoginError(`Sign-in failed (${response.status}).`, response.status);
  const data = await readTokens(response, 'POST /auth/login');
  if (!data) throw new LoginError('Sign-in failed: the server response was not understood.', response.status);
  applyTokens(data, name, generation);
}

async function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;
  const startedIn = generation;
  refreshInFlight = (async () => {
    try {
      const token = internal.refreshToken;
      if (!token) throw new AuthRequiredError();
      const response = await postJson('/auth/refresh', { refresh_token: token });
      if (response.status === 401 || response.status === 400) {
        clearSession(SESSION_ENDED_NOTICE);
        throw new AuthRequiredError();
      }
      if (!response.ok) throw new Error(`Token refresh failed: ${response.status}`);
      const data = await readTokens(response, 'POST /auth/refresh');
      if (!data) throw new Error('Token refresh failed: unexpected response'); // transient: the session is kept
      if (startedIn !== generation) throw new AuthRequiredError();
      applyTokens(data, internal.username ?? '', startedIn);
      return data.access_token;
    } finally {
      // Always clear, success OR failure: otherwise one failed refresh leaves a
      // rejected promise here and every later call returns it forever.
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function devDemoLogin(): Promise<boolean> {
  if (!DEV_DEMO || devDemoDisabled) return false;
  try {
    await login(DEV_DEMO.username, DEV_DEMO.password);
    return true;
  } catch {
    return false;
  }
}

/**
 * Call once at startup. Restores a session from the stored refresh token (reload),
 * or in development with VITE_DEMO_* set, signs in as the demo account.
 */
export function initAuth(): Promise<void> {
  if (initPromise) return initPromise;
  initPromise = (async () => {
    const stored = readStored();
    if (stored) {
      internal = { ...EMPTY, refreshToken: stored.refreshToken, username: stored.username };
      status = 'restoring';
      publish();
      try {
        await refreshAccessToken();
      } catch (e) {
        if (!(e instanceof AuthRequiredError)) {
          // Server unreachable etc.: signed out for now, but keep the stored token for a later try.
          clearSession('Could not reach the server to restore your session.', true);
        }
      }
      return;
    }
    await devDemoLogin();
  })();
  return initPromise;
}

/** An access token that is valid right now, refreshing it first if it is close to expiry. */
export async function getToken(): Promise<string> {
  if (internal.accessToken && internal.expiresAtMs - REFRESH_MARGIN_MS > Date.now()) {
    return internal.accessToken;
  }
  if (internal.refreshToken) return refreshAccessToken();
  throw new AuthRequiredError();
}

/** Force a new access token (e.g. after the server answered 401). */
export async function forceRefresh(): Promise<string> {
  if (internal.refreshToken) return refreshAccessToken();
  throw new AuthRequiredError();
}

/**
 * End the session because the server stopped accepting it (e.g. the live socket was refused twice with an
 * "unauthenticated" close even after a refresh). Shows the sign-in screen with the "Session ended" notice.
 * No server call: the credentials are already known to be rejected.
 */
export function endSession(message: string = SESSION_ENDED_NOTICE): void {
  clearSession(message);
}

/** Sign out: the UI is signed out immediately; the server-side revocation is best-effort. */
export async function logout(): Promise<void> {
  const token = internal.refreshToken;
  devDemoDisabled = true; // an explicit sign-out must not be undone by the dev auto-login
  clearSession();
  if (!token) return;
  try {
    await postJson('/auth/logout', { refresh_token: token });
  } catch {
    // Offline: the token is still revoked server-side when it expires or is rotated.
  }
}
