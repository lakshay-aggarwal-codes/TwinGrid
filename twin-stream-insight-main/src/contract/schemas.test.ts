/**
 * Schema behaviour tests. The objects below are TEST-LOCAL minimal shapes used to exercise the schemas
 * (required/optional, enums, errors). They are NOT fixtures, are never shipped, and say nothing about what the
 * backend actually returns -- that is fixtures.test.ts's job, against real captures.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { z } from 'zod';

vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));
import { reportError } from '@/lib/errorReporter.ts';

import {
  AlertRecord,
  ApiHealth,
  ContractError,
  Facility,
  isUnknown,
  LiveFrame,
  OptimizeResult,
  isFailure,
  isSuccess,
  parseApi,
  StateResponse,
  TokenResponse,
  WhatIfResponse,
} from './index';

const state = () => ({
  timestamp: '2026-01-01T12:35:00',
  server_utilisation: 0.5,
  outside_temp_C: 20,
  server_inlet_temp_C: 22,
  server_outlet_temp_C: 30,
  it_power_kw: 100,
  cooling_power_kw: 20,
  total_power_kw: 120,
  pue: 1.2,
  water_flow_lpm: 50,
  water_consumed_L: 10,
  wue: 0.5,
  humidity_pct: 40,
  water_pressure_bar: 2,
  cooling_mode: 'hybrid',
  anomaly: 0,
});
const whatif = () => ({
  hours: 24,
  basis: 'b',
  mean_pue: 1.3,
  wue: 0.4,
  total_water_L: 1000,
  total_energy_kwh: 5000,
  total_co2_kg: 100,
  max_outlet_temp_C: 33,
  final_cooling_mode: 'free_air',
  drought_override_active: false,
  carbon_data_is_real: false,
});
const alert = () => ({
  id: 1,
  created_at: '2026-10-06T10:00:00',
  type: 'anomaly',
  message: 'm',
  severity: 'WARNING',
  score: 0.9,
  alert: true,
  acknowledged: false,
  acknowledged_by: null,
  acknowledged_at: null,
});
const summary = () => ({
  mean_pue: 1.2,
  mean_wue: 0.4,
  mean_cooling_power_kw: 20,
  total_water_consumed_L: 100,
  total_reward: 1,
  safety_violations: 0,
});
const facility = () => ({ id: 1, name: 'f', frame_unit: 'm', frame_note: 'n', created_at: '2026-01-01T00:00:00+00:00' });
const token = () => ({ access_token: 'a', refresh_token: 'r', token_type: 'bearer', role: 'viewer' });
const health = () => ({ status: 'healthy', timestamp: '2026-10-06T10:00:00' });

beforeEach(() => vi.mocked(reportError).mockClear());

/** Every required top-level key, removed one at a time, must fail with exactly that path. */
function mutationCases(schema: z.ZodObject<z.ZodRawShape>, sample: () => Record<string, unknown>) {
  const required = Object.entries(schema.shape)
    .filter(([, t]) => !(t as z.ZodTypeAny).isOptional())
    .map(([k]) => k);
  expect(required.length).toBeGreaterThan(0);
  for (const key of required) {
    const broken = sample();
    delete broken[key];
    const r = parseApi(schema, broken, 'mutation');
    expect(r.ok, `dropping "${key}" must fail`).toBe(false);
    if (isFailure(r)) expect(r.error.issues.map((i) => i.path)).toContain(key);
  }
}

describe('required-field mutation (drop a field -> ContractError with its path)', () => {
  it.each([
    ['StateResponse', StateResponse, state],
    ['LiveFrame', LiveFrame, state],
    ['WhatIfResponse', WhatIfResponse, whatif],
    ['AlertRecord', AlertRecord, alert],
    ['Facility', Facility, facility],
    ['TokenResponse', TokenResponse, token],
    ['ApiHealth', ApiHealth, health],
  ])('%s', (_n, schema, sample) => {
    mutationCases(schema as never, sample as never);
  });

  it('nested path is reported with an index (simulate/optimize results)', () => {
    const bad = state();
    delete (bad as Record<string, unknown>).pue;
    const r = parseApi(OptimizeResult, { results: [state(), bad], summary: summary() }, 'optimize');
    expect(r.ok).toBe(false);
    if (isFailure(r)) expect(r.error.issues.map((i) => i.path)).toContain('results[1].pue');
  });
});

describe('no defaulting', () => {
  it('a missing required value fails; it is not turned into 0', () => {
    const s = state();
    delete (s as Record<string, unknown>).wue;
    expect(parseApi(StateResponse, s, 'state').ok).toBe(false);
  });
  it('a missing optional value stays absent', () => {
    const r = parseApi(StateResponse, state(), 'state');
    expect(isSuccess(r)).toBe(true);
    expect(isSuccess(r) && 'water_stress' in r.data).toBe(false);
    expect(isSuccess(r) && 'carbon_data_is_real' in r.data).toBe(false);
  });
  it('rejects null/NaN-like for a required number', () => {
    expect(parseApi(StateResponse, { ...state(), pue: null }, 's').ok).toBe(false);
    expect(parseApi(StateResponse, { ...state(), pue: '1.2' }, 's').ok).toBe(false);
  });
});

describe('older backend: provenance fields are optional on the live frame', () => {
  it('a bare state parses as a LiveFrame with no origin/seq/ts_ingest/anomaly_status', () => {
    const r = parseApi(LiveFrame, state(), 'live');
    expect(r.ok).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.origin).toBeUndefined();
      expect(r.data.seq).toBeUndefined();
      expect(r.data.anomaly_status).toBeUndefined();
    }
  });
  it('the backend error-branch anomaly_status (status/message/detector_id/trained_on only) parses', () => {
    const r = parseApi(
      LiveFrame,
      { ...state(), origin: 'simulated', seq: 3, anomaly_status: { status: 'error', message: 'x', detector_id: 'd', trained_on: 'synthetic' } },
      'live',
    );
    expect(r.ok).toBe(true);
  });
  it('anomaly_status without status or message fails', () => {
    expect(parseApi(LiveFrame, { ...state(), anomaly_status: { message: 'x' } }, 'live').ok).toBe(false);
    expect(parseApi(LiveFrame, { ...state(), anomaly_status: { status: 'ok' } }, 'live').ok).toBe(false);
  });
});

describe('unknown enum values never throw and stay unknown', () => {
  it('cooling_mode, origin, severity, anomaly status, role, health status', () => {
    const live = parseApi(
      LiveFrame,
      { ...state(), cooling_mode: 'plasma', origin: 'quantum', anomaly_status: { status: 'degraded-new', message: 'm' } },
      'live',
    );
    expect(live.ok).toBe(true);
    if (isSuccess(live)) {
      expect(isUnknown(live.data.cooling_mode) && live.data.cooling_mode.value).toBe('plasma');
      expect(isUnknown(live.data.origin) && live.data.origin.value).toBe('quantum');
      expect(isUnknown(live.data.anomaly_status?.status) && live.data.anomaly_status.status.value).toBe('degraded-new');
    }
    const a = parseApi(AlertRecord, { ...alert(), severity: 'FATAL' }, 'alert');
    expect(isSuccess(a) && isUnknown(a.data.severity)).toBe(true);
    const t = parseApi(TokenResponse, { ...token(), role: 'admin' }, 'login');
    expect(isSuccess(t) && isUnknown(t.data.role)).toBe(true);
    const h = parseApi(ApiHealth, { ...health(), status: 'on-fire' }, 'health');
    expect(isSuccess(h) && isUnknown(h.data.status)).toBe(true);
  });
  it('known values stay plain strings, not Unknown', () => {
    const r = parseApi(LiveFrame, { ...state(), origin: 'simulated' }, 'live');
    expect(isSuccess(r)).toBe(true);
    expect(isSuccess(r) && r.data.origin).toBe('simulated');
    expect(isSuccess(r) && isUnknown(r.data.cooling_mode)).toBe(false);
  });
  it('a non-string in an enum position still fails (it is not an unknown value, it is a broken payload)', () => {
    expect(parseApi(StateResponse, { ...state(), cooling_mode: 7 }, 's').ok).toBe(false);
    expect(parseApi(StateResponse, { ...state(), cooling_mode: null }, 's').ok).toBe(false);
  });
});

describe('extra fields are tolerated and preserved', () => {
  it('additive backend fields do not fail and are not stripped', () => {
    const r = parseApi(LiveFrame, { ...state(), carbon_semantic: 'x', brand_new_field: { a: 1 } }, 'live');
    expect(r.ok).toBe(true);
    if (isSuccess(r)) expect((r.data as Record<string, unknown>).brand_new_field).toEqual({ a: 1 });
  });
});

describe('ContractError / parseApi', () => {
  it('returns a discriminated result and reports exactly once on failure', () => {
    const r = parseApi(StateResponse, { nope: 1 }, 'GET /api/state');
    expect(r.ok).toBe(false);
    if (isFailure(r)) {
      expect(r.error).toBeInstanceOf(ContractError);
      expect(r.error.context).toBe('GET /api/state');
    }
    expect(reportError).toHaveBeenCalledTimes(1);
    expect(vi.mocked(reportError).mock.calls[0][0]).toBe('contract.GET /api/state');
  });
  it('does not report on success', () => {
    expect(parseApi(StateResponse, state(), 's').ok).toBe(true);
    expect(reportError).not.toHaveBeenCalled();
  });
  it('carries paths and codes only: no payload values anywhere in the error', () => {
    const SECRET = 'SECRET-VALUE-12345';
    const r = parseApi(StateResponse, { ...state(), pue: SECRET, cooling_mode: 99, humidity_pct: SECRET, extra: SECRET }, 'state');
    expect(r.ok).toBe(false);
    if (isFailure(r)) {
      const dump = JSON.stringify({ m: r.error.message, i: r.error.issues, s: r.error.stack?.split('\n')[0] });
      expect(dump).not.toContain(SECRET);
      expect(dump).not.toContain('99');
      expect(Object.keys(r.error.issues[0]).sort()).toEqual(['code', 'path']);
    }
    const reported = vi.mocked(reportError).mock.calls[0][1] as ContractError;
    expect(JSON.stringify({ m: reported.message, i: reported.issues })).not.toContain(SECRET);
  });
  it('truncates a long path list in the message but keeps every issue', () => {
    const r = parseApi(StateResponse, {}, 'state');
    expect(r.ok).toBe(false);
    if (isFailure(r)) {
      expect(r.error.issues.length).toBeGreaterThan(5);
      expect(r.error.message).toMatch(/\(\+\d+ more\)/);
    }
  });
  it('a non-object payload fails at the root without throwing', () => {
    for (const bad of [null, undefined, 'x', 3, []]) {
      const r = parseApi(StateResponse, bad, 'state');
      expect(r.ok).toBe(false);
      if (isFailure(r)) expect(r.error.issues[0].path).toBe('(root)');
    }
  });
});
