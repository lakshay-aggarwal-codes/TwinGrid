import { API_BASE_URL, assertApiConfigured } from './config.ts';

const DEMO_USERNAME = import.meta.env.VITE_DEMO_USERNAME as string | undefined;
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD as string | undefined;

interface CachedToken {
  token: string;
  expiresAtMs: number;
}

let cached: CachedToken | null = null;
let inFlight: Promise<string> | null = null;
 
const REFRESH_MARGIN_MS = 5 * 60 * 1000;

async function login(): Promise<string> {
  if (!DEMO_USERNAME || !DEMO_PASSWORD) {
    throw new Error(
      'VITE_DEMO_USERNAME / VITE_DEMO_PASSWORD are not set. Copy .env.example to .env ' +
        'and fill these in with the account created by scripts/create_demo_user.py.'
    );
  }
  assertApiConfigured();
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: DEMO_USERNAME, password: DEMO_PASSWORD }),
  });
  if (!response.ok) {
    throw new Error(`Login failed: ${response.status} ${response.statusText}`);
  }
  const data = (await response.json()) as { access_token: string };
  return data.access_token;
}

function decodeExpiryMs(token: string): number {
  try {
    // JWTs are base64url ("-" and "_"); atob() only understands plain base64.
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(b64));
    if (typeof payload.exp === 'number') return payload.exp * 1000;
  } catch {
    // fall through
  } 
  return Date.now() + 10 * 60 * 1000;
}
 
export async function getToken(): Promise<string> {
  const now = Date.now();
  if (cached && cached.expiresAtMs - REFRESH_MARGIN_MS > now) {
    return cached.token;
  }
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const token = await login();
      cached = { token, expiresAtMs: decodeExpiryMs(token) };
      return token;
    } finally {
      // Always clear, success OR failure: otherwise one failed login leaves a
      // rejected promise in `inFlight` and every later call returns it forever.
      inFlight = null;
    }
  })();

  return inFlight;
}