#!/usr/bin/env node
/**
 * FE-01 / FE-11: capture REAL responses from a RUNNING backend, and detect contract drift against the committed ones.
 *
 * Fixtures are real captures, not hand-edited. The only transformation is redaction of credentials
 * (login tokens), recorded in each fixture's `_meta.redactions`.
 *
 * CAPTURE (Node >= 22: global fetch + WebSocket):
 *   TWINGRID_API_BASE_URL=http://localhost:8000 \
 *   TWINGRID_USERNAME=operator TWINGRID_PASSWORD=... \
 *   [TWINGRID_BACKEND_HASH=<git sha>] [CAPTURE_LIVE_FRAMES=3] [CAPTURE_TIMEOUT_MS=30000] \
 *   node scripts/capture-contract.mjs [--out <dir>]
 *   Default output: src/contract/fixtures (committed set). With --out the committed set is left untouched.
 *   Also snapshots the OpenAPI property names of the typed models (auth, facility) to <out>/openapi/typed.json.
 *   Use an operator account to also capture POST /api/optimize (viewer gets 403 and it is skipped + logged).
 *
 * DRIFT (offline, no backend):
 *   node scripts/capture-contract.mjs --diff <committedDir> <freshDir>
 *   Exits 1 when a fixture is missing from either side, an endpoint/method/status changed, or a body SHAPE changed
 *   (key added/removed, type changed). Values are never compared: they change on every capture. null matches any
 *   type and an empty array matches any array (the shape cannot be inferred from them).
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_FIXTURES = join(ROOT, 'src', 'contract', 'fixtures');
const LOG_FILE = join(ROOT, 'docs', 'frontend', 'contracts', 'capture.log');

/** Backend OpenAPI component names whose property names are compared with the zod schemas (FE-11). */
export const TYPED_OPENAPI_MODELS = [
  'TokenResponse',
  'FacilityOut',
  'PoseOut',
  'LocatedInOut',
  'AssetOut',
  'AssetsResponse',
  'EdgeOut',
  'EdgesResponse',
];

// ------------------------------------------------------------------ drift detection (pure, offline)

/**
 * Structural shape of a JSON value. Objects -> {key: shape}; arrays -> {$array: merged element shape | 'empty'};
 * primitives -> 'string' | 'number' | 'boolean' | 'null'. Merging array elements unions their keys.
 */
export function shapeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) {
    if (value.length === 0) return { $array: 'empty' };
    return { $array: value.map(shapeOf).reduce(mergeShapes) };
  }
  if (typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shapeOf(v)]));
  }
  return typeof value;
}

function isObjectShape(s) {
  return typeof s === 'object' && s !== null && !('$array' in s);
}

function mergeShapes(a, b) {
  if (a === 'null') return b;
  if (b === 'null') return a;
  if (a === 'empty') return b;
  if (b === 'empty') return a;
  if (isObjectShape(a) && isObjectShape(b)) {
    const out = { ...a };
    for (const [k, v] of Object.entries(b)) out[k] = k in out ? mergeShapes(out[k], v) : v;
    return out;
  }
  if (typeof a === 'object' && typeof b === 'object' && '$array' in a && '$array' in b) {
    return { $array: mergeShapes(a.$array, b.$array) };
  }
  return a; // a type conflict inside one array is reported by diffShapes against the other side
}

/** Human-readable differences between two shapes; empty list = same shape. */
export function diffShapes(committed, fresh, path = '$') {
  if (committed === 'null' || fresh === 'null') return [];
  if (typeof committed === 'object' && typeof fresh === 'object' && '$array' in committed && '$array' in fresh) {
    if (committed.$array === 'empty' || fresh.$array === 'empty') return [];
    return diffShapes(committed.$array, fresh.$array, `${path}[]`);
  }
  if (isObjectShape(committed) && isObjectShape(fresh)) {
    const out = [];
    for (const k of Object.keys(committed)) {
      if (!(k in fresh)) out.push(`removed  ${path}.${k}`);
      else out.push(...diffShapes(committed[k], fresh[k], `${path}.${k}`));
    }
    for (const k of Object.keys(fresh)) if (!(k in committed)) out.push(`added    ${path}.${k}`);
    return out;
  }
  const label = (s) => (typeof s === 'string' ? s : '$array' in s ? 'array' : 'object');
  return label(committed) === label(fresh) ? [] : [`type     ${path}: ${label(committed)} -> ${label(fresh)}`];
}

function readFixtures(dir) {
  const out = new Map();
  if (!existsSync(dir)) return out;
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (f.endsWith('.json') && statSync(p).isFile()) out.set(f.replace(/\.json$/, ''), JSON.parse(readFileSync(p, 'utf8')));
  }
  return out;
}

/** Compare two fixture directories. Returns the list of drift findings (empty = no drift). */
export function compareFixtureDirs(committedDir, freshDir) {
  const committed = readFixtures(committedDir);
  const fresh = readFixtures(freshDir);
  const findings = [];
  if (committed.size === 0) findings.push(`no committed fixtures in ${committedDir}: capture and commit them first (drift cannot be measured)`);
  for (const [name, c] of committed) {
    const f = fresh.get(name);
    if (!f) {
      findings.push(`${name}: committed fixture has no fresh capture (endpoint gone, failed, or not reachable with this account)`);
      continue;
    }
    for (const key of ['endpoint', 'method', 'http_status']) {
      if (c._meta?.[key] !== f._meta?.[key]) findings.push(`${name}: _meta.${key} ${JSON.stringify(c._meta?.[key])} -> ${JSON.stringify(f._meta?.[key])}`);
    }
    for (const d of diffShapes(shapeOf(c.body), shapeOf(f.body))) findings.push(`${name}: ${d}`);
  }
  for (const name of fresh.keys()) if (!committed.has(name)) findings.push(`${name}: fresh capture is not committed (new endpoint or shape; commit it deliberately)`);
  return findings;
}

/** The OpenAPI snapshot is compared by property names (committed vs fresh). */
export function compareOpenapiSnapshots(committedPath, freshPath) {
  if (!existsSync(committedPath)) return [`no committed OpenAPI snapshot at ${committedPath}`];
  if (!existsSync(freshPath)) return [`no fresh OpenAPI snapshot at ${freshPath}`];
  const c = JSON.parse(readFileSync(committedPath, 'utf8')).schemas ?? {};
  const f = JSON.parse(readFileSync(freshPath, 'utf8')).schemas ?? {};
  const findings = [];
  for (const name of TYPED_OPENAPI_MODELS) {
    if (!c[name] || !f[name]) {
      findings.push(`openapi ${name}: ${!c[name] ? 'not in committed snapshot' : 'not in fresh snapshot'}`);
      continue;
    }
    for (const p of c[name].properties) if (!f[name].properties.includes(p)) findings.push(`openapi ${name}: property removed ${p}`);
    for (const p of f[name].properties) if (!c[name].properties.includes(p)) findings.push(`openapi ${name}: property added ${p}`);
    for (const r of c[name].required) if (!f[name].required.includes(r)) findings.push(`openapi ${name}: ${r} no longer required`);
    for (const r of f[name].required) if (!c[name].required.includes(r)) findings.push(`openapi ${name}: ${r} became required`);
  }
  return findings;
}

/** Reduce a full /openapi.json to {Model: {properties, required}} for the typed models only. */
export function typedOpenapiSnapshot(openapi) {
  const components = openapi?.components?.schemas ?? {};
  const schemas = {};
  for (const name of TYPED_OPENAPI_MODELS) {
    const s = components[name];
    if (!s) continue;
    schemas[name] = { properties: Object.keys(s.properties ?? {}).sort(), required: [...(s.required ?? [])].sort() };
  }
  return schemas;
}

// ------------------------------------------------------------------ capture (needs a running backend)

async function capturePhase(outDir) {
  const env = process.env;
  const BASE = (env.TWINGRID_API_BASE_URL ?? '').replace(/\/+$/, '');
  const USER = env.TWINGRID_USERNAME ?? '';
  const PASS = env.TWINGRID_PASSWORD ?? '';
  const BACKEND_HASH = env.TWINGRID_BACKEND_HASH || null;
  const LIVE_FRAMES = Math.min(Math.max(Number(env.CAPTURE_LIVE_FRAMES ?? 1) || 1, 1), 10);
  const TIMEOUT_MS = Number(env.CAPTURE_TIMEOUT_MS ?? 30000) || 30000;

  const logLines = [];
  const log = (msg) => {
    const line = `${new Date().toISOString()} ${msg}`;
    logLines.push(line);
    console.log(line);
  };
  const flushLog = async () => {
    await mkdir(dirname(LOG_FILE), { recursive: true });
    await writeFile(LOG_FILE, logLines.join('\n') + '\n');
  };
  const fail = async (msg) => {
    await flushLog();
    console.error(msg);
    process.exit(1);
  };

  if (!BASE || !USER || !PASS) await fail('Set TWINGRID_API_BASE_URL, TWINGRID_USERNAME and TWINGRID_PASSWORD (see header of this script).');
  const host = new URL(BASE).host; // host only: no path, no credentials
  const secrets = [PASS];

  const assertNoSecrets = (name, body) => {
    const text = JSON.stringify(body);
    for (const s of secrets) {
      if (s && s.length >= 6 && text.includes(s)) throw new Error(`refusing to write ${name}: body contains a secret`);
    }
  };

  async function save(name, endpoint, method, status, body, redactions = []) {
    assertNoSecrets(name, body);
    const fixture = {
      _meta: { endpoint, method, http_status: status, captured_at: new Date().toISOString(), base_url_host: host, backend_hash: BACKEND_HASH, redactions },
      body,
    };
    await mkdir(outDir, { recursive: true });
    await writeFile(join(outDir, `${name}.json`), JSON.stringify(fixture, null, 2) + '\n');
    log(`SAVED   ${name}.json  (${method} ${endpoint} -> ${status})`);
  }

  async function call(method, path, { token, json } = {}) {
    const res = await fetch(`${BASE}${path}`, {
      method,
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { ...(json ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
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
    await new Promise((resolveLive) => {
      let received = 0;
      let saved = 0;
      const ws = new WebSocket(wsUrl);
      const timer = setTimeout(() => {
        log(`FAILED  live_frame: only ${saved}/${LIVE_FRAMES} frame(s) within ${TIMEOUT_MS} ms`);
        ws.close();
        resolveLive();
      }, TIMEOUT_MS);
      ws.onmessage = async (ev) => {
        received += 1;
        if (received > LIVE_FRAMES) return; // ignore frames beyond the requested count
        const n = received;
        try {
          await save(n === 1 ? 'live_frame' : `live_frame_${n}`, '/ws/live', 'WS', 101, JSON.parse(String(ev.data)));
        } catch (e) {
          log(`FAILED  live_frame_${n}: ${e.message}`);
        }
        saved += 1;
        if (saved >= LIVE_FRAMES) {
          clearTimeout(timer);
          ws.close();
          resolveLive();
        }
      };
      ws.onerror = () => log('NOTE    live websocket error event (browser-style WS gives no detail)');
      ws.onclose = (ev) => {
        if (received === 0) {
          clearTimeout(timer);
          log(`FAILED  live_frame: socket closed before any frame (code ${ev.code})`);
          resolveLive();
        }
      };
    });
  }

  log(`capture start: host=${host} backend_hash=${BACKEND_HASH ?? 'not provided'} live_frames=${LIVE_FRAMES} out=${outDir}`);

  let login;
  try {
    login = await call('POST', '/auth/login', { json: { username: USER, password: PASS } });
  } catch (e) {
    log(`FAILED  login: ${e.name}: ${e.cause?.code ?? e.message}`);
    await fail(`cannot reach ${host}: ${e.cause?.code ?? e.message}`);
  }
  if (!login.ok || !login.body?.access_token) await fail(`login failed: HTTP ${login.status}`);
  const token = login.body.access_token;
  secrets.push(token, login.body.refresh_token);
  await save('auth_login', '/auth/login', 'POST', login.status, { ...login.body, access_token: '<redacted>', refresh_token: '<redacted>' }, ['access_token', 'refresh_token']);
  log(`role reported by backend: ${login.body.role}`);

  const t = { token };
  await capture('health_api', 'GET', '/api/health', t);
  await capture('healthz', 'GET', '/healthz');
  await capture('state', 'GET', '/api/state?utilisation=0.5&outside_temp=25&water_stress=0&mode=auto', t);
  await capture('simulate', 'GET', '/api/simulate/2?utilisation=0.7&outside_temp=25&stress=0.3', t);
  await capture('whatif', 'GET', '/api/whatif?utilisation=0.65&outside_temp=22&water_stress=0&mode=auto&chilled_water_temp=7', t);
  const alerts = await capture('alerts', 'GET', '/api/alerts?limit=5', t);
  if (Array.isArray(alerts) && alerts.length === 0) log('NOTE    alerts fixture is an EMPTY list: AlertRecord is not exercised. Re-capture once an alert exists.');
  await capture('equipment_health', 'GET', '/api/equipment/health', t);
  await capture('optimize', 'POST', '/api/optimize', { ...t, json: { alpha: 0.5, beta: 0.3, gamma: 0.2, water_stress: 0, hours: 2 } });
  await capture('facility', 'GET', '/api/facility', t);
  const assets = await capture('assets', 'GET', '/api/assets?limit=20', t);
  const firstAsset = assets?.assets?.[0]?.id;
  if (firstAsset !== undefined) await capture('edges', 'GET', `/api/assets/${firstAsset}/edges`, t);
  else log('SKIPPED edges: no asset available from /api/assets');
  await captureLive(token);

  // FE-11: the typed models' property names, from the backend's own OpenAPI document.
  try {
    const spec = await call('GET', '/openapi.json');
    if (spec.ok && spec.body) {
      const schemas = typedOpenapiSnapshot(spec.body);
      const missing = TYPED_OPENAPI_MODELS.filter((n) => !(n in schemas));
      if (missing.length) log(`NOTE    OpenAPI has no component named: ${missing.join(', ')}`);
      await mkdir(join(outDir, 'openapi'), { recursive: true });
      await writeFile(
        join(outDir, 'openapi', 'typed.json'),
        JSON.stringify({ _meta: { endpoint: '/openapi.json', method: 'GET', http_status: spec.status, captured_at: new Date().toISOString(), base_url_host: host, backend_hash: BACKEND_HASH }, schemas }, null, 2) + '\n'
      );
      log(`SAVED   openapi/typed.json (${Object.keys(schemas).length}/${TYPED_OPENAPI_MODELS.length} typed models)`);
    } else {
      log(`SKIPPED openapi/typed.json: GET /openapi.json -> HTTP ${spec.status}`);
    }
  } catch (e) {
    log(`FAILED  openapi/typed.json: ${e.name}: ${e.message}`);
  }

  log('capture end');
  await flushLog();
}

// ------------------------------------------------------------------ CLI

async function main(argv) {
  const diffAt = argv.indexOf('--diff');
  if (diffAt !== -1) {
    const [committed, fresh] = [argv[diffAt + 1], argv[diffAt + 2]];
    if (!committed || !fresh) {
      console.error('usage: capture-contract.mjs --diff <committedDir> <freshDir>');
      process.exit(2);
    }
    const findings = [
      ...compareFixtureDirs(resolve(committed), resolve(fresh)),
      ...compareOpenapiSnapshots(join(resolve(committed), 'openapi', 'typed.json'), join(resolve(fresh), 'openapi', 'typed.json')),
    ];
    if (findings.length) {
      console.error(`CONTRACT DRIFT: ${findings.length} finding(s)`);
      for (const f of findings) console.error(`  - ${f}`);
      process.exit(1);
    }
    console.log('contract drift: none (shapes and typed-model property names match the committed set)');
    return;
  }
  const outAt = argv.indexOf('--out');
  await capturePhase(outAt !== -1 ? resolve(argv[outAt + 1]) : DEFAULT_FIXTURES);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main(process.argv.slice(2));
}
