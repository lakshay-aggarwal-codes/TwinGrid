import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { UNITS, percentToUtilisation, unitFor, utilisationToPercent } from './units';
import { StateResponse } from './schemas/state';
import { LiveFrame, AnomalyStatusPayload } from './schemas/live';
import { WhatIfResponse } from './schemas/whatif';
import { OptimizeSummary } from './schemas/optimize';
import { AlertRecord } from './schemas/alert';
import { EquipmentHealth } from './schemas/equipmentHealth';
import { Pose } from './schemas/facility';

function unwrap(t: z.ZodTypeAny): z.ZodTypeAny {
  let cur = t;
  for (;;) {
    const d = cur._def as { innerType?: z.ZodTypeAny; schema?: z.ZodTypeAny };
    if (d.innerType) cur = d.innerType;
    else if (d.schema) cur = d.schema;
    else return cur;
  }
}

function numericKeys(schema: z.ZodObject<z.ZodRawShape>, exclude: string[] = []): string[] {
  return Object.entries(schema.shape)
    .filter(([k, t]) => !exclude.includes(k) && unwrap(t as z.ZodTypeAny) instanceof z.ZodNumber)
    .map(([k]) => k);
}

// Identifiers / counters / sequence numbers are not measurements and carry no unit.
const NON_MEASUREMENT = ['schema_version', 'seq', 'window_size', 'window_filled', 'id'];

describe('unit table completeness vs schema numeric fields', () => {
  const cases: Array<[string, z.ZodObject<z.ZodRawShape>, string[]]> = [
    ['StateResponse', StateResponse as never, []],
    ['LiveFrame', LiveFrame as never, NON_MEASUREMENT],
    ['AnomalyStatusPayload', AnomalyStatusPayload as never, NON_MEASUREMENT],
    ['WhatIfResponse', WhatIfResponse as never, []],
    ['OptimizeSummary', OptimizeSummary as never, []],
    ['AlertRecord', AlertRecord as never, NON_MEASUREMENT],
    ['EquipmentHealth', EquipmentHealth as never, []],
    ['Pose', Pose as never, []],
  ];
  it.each(cases)('%s: every numeric field has a unit entry', (_name, schema, exclude) => {
    const keys = numericKeys(schema, exclude);
    expect(keys.length).toBeGreaterThan(0);
    const missing = keys.filter((k) => unitFor(k) === undefined);
    expect(missing).toEqual([]);
  });
});

describe('unit table content', () => {
  it('server_utilisation is a documented 0-1 fraction, shown without a unit (UQ-1, ADR 004)', () => {
    const info = unitFor('server_utilisation');
    expect(info?.source).toBe('documented');
    expect(info?.unit).toBeNull();
    expect(info?.range).toEqual([0, 1]);
  });
  it('an unverified entry never carries a unit', () => {
    for (const [field, info] of Object.entries(UNITS)) {
      if (info.source === 'unverified') expect({ field, unit: info.unit }).toEqual({ field, unit: null });
    }
  });
  it('every entry is well-formed', () => {
    for (const [field, info] of Object.entries(UNITS)) {
      expect(['field-name', 'documented', 'unverified']).toContain(info.source);
      expect(Number.isInteger(info.precision) && info.precision >= 0).toBe(true);
      expect({ field, label: info.label.length > 0 }).toEqual({ field, label: true });
    }
  });
  it('unitFor does not resolve inherited object keys', () => {
    expect(unitFor('constructor')).toBeUndefined();
    expect(unitFor('toString')).toBeUndefined();
  });
});

describe('server_utilisation unit boundary (UQ-1, ADR 004)', () => {
  const OK_STATE = {
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
  };
  const OK_WHATIF = {
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
    inputs: { utilisation: 0.65, outside_temp_C: 22, water_stress: 0.4, mode: 'auto', chilled_water_temp_C: 18 },
  };
  const state = (u: number) => ({ ...OK_STATE, server_utilisation: u });

  it('the response schema accepts a fraction and rejects a percentage', () => {
    for (const ok of [0, 0.5, 1]) expect(StateResponse.safeParse(state(ok)).success).toBe(true);
    for (const bad of [65, 100, 1.01, -0.01]) expect(StateResponse.safeParse(state(bad)).success).toBe(false);
  });

  it('the what-if echo of the request uses the same unit', () => {
    const inputs = (u: number) => ({ ...OK_WHATIF, inputs: { ...OK_WHATIF.inputs, utilisation: u } });
    expect(WhatIfResponse.safeParse(inputs(0.65)).success).toBe(true);
    expect(WhatIfResponse.safeParse(inputs(65)).success).toBe(false);
  });

  it('fraction -> percent for display, and null (no number shown) outside [0, 1]', () => {
    expect(utilisationToPercent(0.65)).toBeCloseTo(65, 9);
    expect(utilisationToPercent(0)).toBe(0);
    expect(utilisationToPercent(1)).toBe(100);
    for (const bad of [65, -0.1, 1.0001, Number.NaN, Number.POSITIVE_INFINITY]) expect(utilisationToPercent(bad)).toBeNull();
  });

  it('percent -> fraction for requests, and null outside [0, 100]', () => {
    expect(percentToUtilisation(65)).toBeCloseTo(0.65, 9);
    expect(percentToUtilisation(100)).toBe(1);
    for (const bad of [-1, 100.5, Number.NaN]) expect(percentToUtilisation(bad)).toBeNull();
  });

  it('round trip: the slider percent sent as a fraction comes back as the same percent', () => {
    for (const pct of [10, 25, 65, 100]) expect(utilisationToPercent(percentToUtilisation(pct) as number)).toBeCloseTo(pct, 9);
  });
});
