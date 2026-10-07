/**
 * Runs every REAL captured fixture (scripts/capture-contract.mjs) through its schema.
 * A failure here is a CONTRACT FINDING: record it in docs/frontend/contracts/; do not loosen the schema to pass.
 * Until fixtures are captured the suite reports a todo, not a pass.
 */
import { describe, expect, it, vi } from 'vitest';
import type { z } from 'zod';

vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import {
  AlertList,
  ApiHealth,
  AssetsResponse,
  EdgesResponse,
  EquipmentHealth,
  Facility,
  Healthz,
  LiveFrame,
  OptimizeResult,
  isFailure,
  isSuccess,
  parseApi,
  SimulateResponse,
  StateResponse,
  TokenResponse,
  WhatIfResponse,
} from './index';

interface FixtureFile {
  _meta: { endpoint: string; method: string; http_status: number; captured_at: string; base_url_host: string; backend_hash: string | null; redactions: string[] };
  body: unknown;
}

const modules = import.meta.glob('./fixtures/*.json', { eager: true, import: 'default' }) as Record<string, FixtureFile>;
const entries = Object.entries(modules).map(([path, f]) => ({ name: path.replace(/^.*\/|\.json$/g, ''), fixture: f }));

const SCHEMAS: Record<string, z.ZodTypeAny> = {
  auth_login: TokenResponse,
  health_api: ApiHealth,
  healthz: Healthz,
  state: StateResponse,
  simulate: SimulateResponse,
  whatif: WhatIfResponse,
  alerts: AlertList,
  equipment_health: EquipmentHealth,
  optimize: OptimizeResult,
  facility: Facility,
  assets: AssetsResponse,
  edges: EdgesResponse,
};
const schemaFor = (name: string) => (/^live_frame(_\d+)?$/.test(name) ? LiveFrame : SCHEMAS[name]);

describe.skipIf(entries.length === 0)('captured fixtures', () => {
  it.each(entries.map((e) => [e.name, e.fixture] as const))('%s has capture metadata', (_n, f) => {
    expect(f._meta.captured_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(f._meta.base_url_host.length).toBeGreaterThan(0);
    expect(f._meta.endpoint.length).toBeGreaterThan(0);
    expect('backend_hash' in f._meta).toBe(true);
  });

  it.each(entries.map((e) => [e.name, e.fixture] as const))('%s is mapped to a schema and parses', (name, f) => {
    const schema = schemaFor(name);
    expect(schema, `no schema mapped for fixture "${name}"`).toBeDefined();
    const r = parseApi(schema, f.body, name);
    expect(r.ok, isFailure(r) ? r.error.message : '').toBe(true);
  });

  it.each(entries.map((e) => [e.name, e.fixture] as const))('%s: dropping any required top-level field fails with its path', (name, f) => {
    const schema = schemaFor(name) as z.ZodObject<z.ZodRawShape> | undefined;
    const body = f.body as Record<string, unknown>;
    if (!schema || !('shape' in schema) || typeof body !== 'object' || Array.isArray(body)) return; // arrays: covered by element schema
    const required = Object.entries(schema.shape)
      .filter(([k, t]) => !(t as z.ZodTypeAny).isOptional() && k in body)
      .map(([k]) => k);
    for (const key of required) {
      const broken = { ...body };
      delete broken[key];
      const r = parseApi(schema, broken, name);
      expect(r.ok, `dropping "${key}" from ${name} must fail`).toBe(false);
      if (isFailure(r)) expect(r.error.issues.map((i) => i.path)).toContain(key);
    }
  });

  it('no fixture contains a credential placeholder that was not redacted by the capture script', () => {
    for (const { name, fixture } of entries) {
      const text = JSON.stringify(fixture.body);
      if (name === 'auth_login') {
        expect(fixture._meta.redactions).toEqual(expect.arrayContaining(['access_token', 'refresh_token']));
        expect(text).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}\./); // a JWT header
      }
    }
  });
});

describe('fixture capture status', () => {
  it.skipIf(entries.length > 0)('NO real fixtures captured yet: run scripts/capture-contract.mjs against a live backend (docs/frontend/contracts/README.md)', () => {
    /* intentionally skipped, so the report shows the gap instead of a false pass */
  });
});
