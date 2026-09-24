/**
 * Single source of truth for where the backend lives.
 *
 * VITE_API_BASE_URL is the only setting: e.g. https://your-backend.up.railway.app
 * (a trailing slash is tolerated and stripped). The WebSocket URL is derived from
 * it: https -> wss, http -> ws.
 *
 * In `npm run dev` an unset variable falls back to the local FastAPI server. In a
 * production build there is deliberately NO fallback -- silently talking to a
 * hard-coded host is how authClient and apiClient ended up on two different backends.
 */

const DEV_FALLBACK = 'http://localhost:8000';

/** Pure, exported for tests: normalise a configured base URL. */
export function normalizeBaseUrl(raw: string | undefined | null): string {
  return (raw ?? '').trim().replace(/\/+$/, '');
}

/** Pure, exported for tests: https://h -> wss://h/ws/live, http://h -> ws://h/ws/live. */
export function deriveWsUrl(baseUrl: string): string {
  return `${baseUrl.replace(/^http/i, 'ws')}/ws/live`;
}

const configured = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL as string | undefined);

export const API_BASE_URL: string = configured || (import.meta.env.DEV ? DEV_FALLBACK : '');
export const WS_LIVE_URL: string = API_BASE_URL ? deriveWsUrl(API_BASE_URL) : '';

/** Call before any request so a missing setting fails loudly instead of hitting a relative URL. */
export function assertApiConfigured(): void {
  if (!API_BASE_URL) {
    throw new Error(
      'VITE_API_BASE_URL is not set. Copy .env.example to .env and set it to your backend URL ' +
        '(e.g. https://your-backend.up.railway.app), then rebuild.'
    );
  }
}
