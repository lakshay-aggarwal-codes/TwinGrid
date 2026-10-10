import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { parseApi, isFailure, isSuccess } from '@/contract';
import { ScenarioRegistrySchema } from './schema';
import { CAPTURED_REGISTRY, clone } from './testFixtures';

describe('ScenarioRegistry schema against the G-SCN capture', () => {
  it('the captured registry parses and keeps every descriptor', () => {
    const r = parseApi(ScenarioRegistrySchema, clone(CAPTURED_REGISTRY), 'GET /api/scenarios');
    expect(isSuccess(r)).toBe(true);
    if (isSuccess(r)) {
      expect(r.data.registry_version).toBe('1');
      expect(r.data.scenarios.map((s) => s.id)).toEqual(['whatif-baseline', 'whatif-peak-workload', 'whatif-heat-wave', 'whatif-drought']);
      expect(r.data.scenarios[2].weather_source).toBe('constant_input');
    }
  });

  it('an unknown kind / weather_source / plant / control still parses (they stay unknown strings)', () => {
    const body = clone(CAPTURED_REGISTRY);
    Object.assign(body.scenarios[0], { kind: 'carbon-shock', weather_source: 'ensemble', plant: 'hybrid', control: 'advisory' });
    const r = parseApi(ScenarioRegistrySchema, body, 'GET /api/scenarios');
    expect(isSuccess(r) && r.data.scenarios[0].kind).toBe('carbon-shock');
  });

  it('missing weather/plant fields stay missing (not defaulted)', () => {
    const body = clone(CAPTURED_REGISTRY);
    delete (body.scenarios[0] as Record<string, unknown>).weather_source;
    delete (body.scenarios[0] as Record<string, unknown>).plant;
    const r = parseApi(ScenarioRegistrySchema, body, 'GET /api/scenarios');
    expect(isSuccess(r) && r.data.scenarios[0].weather_source).toBeUndefined();
    expect(isSuccess(r) && r.data.scenarios[0].plant).toBeUndefined();
  });

  it('a duplicate id is a contract failure, not repaired', () => {
    const body = clone(CAPTURED_REGISTRY);
    body.scenarios[1].id = body.scenarios[0].id;
    expect(isFailure(parseApi(ScenarioRegistrySchema, body, 'GET /api/scenarios'))).toBe(true);
  });

  it.each([['no id', { id: '' }], ['no label', { label: '' }]])('rejects a descriptor with %s', (_n, patch) => {
    const body = clone(CAPTURED_REGISTRY);
    Object.assign(body.scenarios[0], patch);
    expect(isFailure(parseApi(ScenarioRegistrySchema, body, 'GET /api/scenarios'))).toBe(true);
  });

  it('a non-array scenarios field is a contract failure', () => {
    expect(isFailure(parseApi(ScenarioRegistrySchema, { registry_version: '1', scenarios: null }, 'GET /api/scenarios'))).toBe(true);
  });
});
