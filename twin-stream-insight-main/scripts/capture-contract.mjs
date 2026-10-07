#!/usr/bin/env node
/**
 * FE-01: capture ONE real response per endpoint from a RUNNING backend into src/contract/fixtures/.
 *
 * Fixtures are real captures, not hand-edited. The only transformation is redaction of credentials
 * (login tokens), recorded in each fixture's `_meta.redactions`.
 *
 * Usage (Node >= 22: global fetch + WebSocket):
 *   TWINGRID_API_BASE_URL=https://api.example.org \
 *   TWINGRID_USERNAME=viewer TWINGRID_PASSWORD=... \
 *   [TWINGRID_BACKEND_HASH=<git sha or content hash>] \
 *   [CAPTURE_LIVE_FRAMES=3] [CAPTURE_TIMEOUT_MS=30000] \
 *   node scripts/capture-contract.mjs
 *
 * Use an operator account to also capture POST /api/optimize (viewer gets 403 and it is skipped + logged).
 * Writes: src/contract/fixtures/<name>.json and docs/frontend/contracts/capture.log
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const FIXTURES = join(ROOT, 'src', 'contract', 'fixtures');
const LOG_FILE = join(ROOT, 'docs', 'frontend', 'contracts', 'capture.log');

const env = process.env;
const BASE = (env.TWINGRID_API_BASE_URL ?? '').replace(/\/+$/, '');
const USER = env.TWINGRID_USERNAME ?? '';
const PASS = env.TWINGRID_PASSWORD ?? '';
const BACKEND_HASH = env.TWINGRID_BACKEND_HASH || null;
const LIVE_FRAMES = Math.min(Math.max(Number(env.CAPTURE_LIVE_FRAMES ?? 1) || 1, 1), 10);
const TIMEOUT_MS = Number(env.CAPTURE_TIMEOUT_MS ?? 30000) || 30000;

const logLines = [];
function log(msg) {
  const line = `${new Date().toISOString()} ${msg}`;
  logLines.push(line);
  console.log(line);
}
async function flushLog() {
  await mkdir(dirname(LOG_FILE), { recursive: true });
  await writeFile(LOG_FILE, logLines.join('\n') + '\n');
}
function fail(msg) {
  console.error(msg);
  process.exit(1);
}

if (!BASE || !USER || !PASS) {
  fail('Set TWINGRID_API_BASE_URL, TWINGRID_USERNAME and TWINGRID_PASSWORD (see header of this script).');
}
const host = new URL(BASE).host; // host only: no path, no credentials
const secrets = [PASS];

function assertNoSecrets(name, body) {
  const text = JSON.stringify(body);
  for (const s of secrets) {
    if (s && s.length >= 6 && text.includes(s)) throw new Error(`refusing to write ${name}: body contains a secret`);
  }
}

async function save(name, endpoint, method, status, body, redactions = []) {
  assertNoSecrets(name, body);
  const fixture = {
    _meta: {
      endpoint,
      method,
      http_status: status,
      captured_at: new Date().toISOString(),
      base_url_host: host,
      backend_hash: BACKEND_HASH,
      redactions,
    },
    body,
  };
  await mkdir(FIXTURES, { recursive: true });
  await writeFile(join(FIXTURES, `${name}.json`), JSON.stringify(fixture, null, 2) + '\n');
  log(`SAVED   ${name}.json  (${method} ${endpoint} -> ${status})`);
}

async function call(method, path, { token, json } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    headers: {
      ...(json ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: json ? JSON.stringify(json) : undefined,
  });
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  return { status: res.status, ok: res.ok, body };
}

async function capture(name, method, path, opts, { redact } = {}) {
  try {
    const r = await call(method, path, opts);
    if (!r.ok) {
      log(`SKIPPED ${name}: ${method} ${path} -> HTTP ${r.status} (not saved; non-2xx is not a fixture)`);
      return null;
    }
    let body = r.body;
    const redactions = [];
    if (redact) {
      body = { ...body };
      for (const key of redact) {
        if (key in body) {
          body[key] = '<redacted>';
          redactions.push(key);
        }
      }
    }
    await save(name, path.split('?')[0], method, r.status, body, redactions);
    return r.body;
  } catch (e) {
    log(`FAILED  ${name}: ${method} ${path} -> ${e.name}: ${e.message}`);
    return null;
  }
}

async function captureLive(token) {
  const wsUrl = BASE.replace(/^http/i, 'ws') + `/ws/live?token=${encodeURIComponent(token)}`;
  await new Promise((resolve) => {
    let received = 0;
    let saved = 0;
    const ws = new WebSocket(wsUrl);
    const timer = setTimeout(() => {
      log(`FAILED  live_frame: only ${saved}/${LIVE_FRAMES} frame(s) within ${TIMEOUT_MS} ms`);
      ws.close();
      resolve();
    }, TIMEOUT_MS);
    ws.onmessage = async (ev) => {
      received += 1;
      if (received > LIVE_FRAMES) return; // ignore frames beyond the requested count
      const n = received;
      try {
        const name = n === 1 ? 'live_frame' : `live_frame_${n}`;
        await save(name, '/ws/live', 'WS', 101, JSON.parse(String(ev.data)));
      } catch (e) {
        log(`FAILED  live_frame_${n}: ${e.message}`);
      }
      saved += 1;
      if (saved >= LIVE_FRAMES) {
        clearTimeout(timer);
        ws.close();
        resolve();
      }
    };
    ws.onerror = () => log('NOTE    live websocket error event (browser-style WS gives no detail)');
    ws.onclose = (ev) => {
      if (received === 0) {
        clearTimeout(timer);
        log(`FAILED  live_frame: socket closed before any frame (code ${ev.code})`);
        resolve();
      }
    };
  });
}

log(`capture start: host=${host} backend_hash=${BACKEND_HASH ?? 'not provided'} live_frames=${LIVE_FRAMES}`);

let login;
try {
  login = await call('POST', '/auth/login', { json: { username: USER, password: PASS } });
} catch (e) {
  log(`FAILED  login: ${e.name}: ${e.cause?.code ?? e.message}`);
  await flushLog();
  fail(`cannot reach ${host}: ${e.cause?.code ?? e.message}`);
}
if (!login.ok || !login.body?.access_token) {
  await flushLog();
  fail(`login failed: HTTP ${login.status}`);
}
const token = login.body.access_token;
secrets.push(token, login.body.refresh_token);
await save('auth_login', '/auth/login', 'POST', login.status, { ...login.body, access_token: '<redacted>', refresh_token: '<redacted>' }, [
  'access_token',
  'refresh_token',
]);
log(`role reported by backend: ${login.body.role}`);

const t = { token };
await capture('health_api', 'GET', '/api/health', t);
await capture('healthz', 'GET', '/healthz');
await capture('state', 'GET', '/api/state?utilisation=0.5&outside_temp=25&water_stress=0&mode=auto', t);
await capture('simulate', 'GET', '/api/simulate/2?utilisation=0.7&outside_temp=25&stress=0.3', t);
await capture('whatif', 'GET', '/api/whatif?utilisation=0.65&outside_temp=22&water_stress=0&mode=auto&chilled_water_temp=7', t);
const alerts = await capture('alerts', 'GET', '/api/alerts?limit=5', t);
if (Array.isArray(alerts) && alerts.length === 0) {
  log('NOTE    alerts fixture is an EMPTY list: AlertRecord is not exercised. Re-capture once an alert exists.');
}
await capture('equipment_health', 'GET', '/api/equipment/health', t);
await capture('optimize', 'POST', '/api/optimize', {
  ...t,
  json: { alpha: 0.5, beta: 0.3, gamma: 0.2, water_stress: 0, hours: 2 },
});
await capture('facility', 'GET', '/api/facility', t);
const assets = await capture('assets', 'GET', '/api/assets?limit=20', t);
const firstAsset = assets?.assets?.[0]?.id;
if (firstAsset !== undefined) await capture('edges', 'GET', `/api/assets/${firstAsset}/edges`, t);
else log('SKIPPED edges: no asset available from /api/assets');
await captureLive(token);

log('capture end');
await flushLog();
