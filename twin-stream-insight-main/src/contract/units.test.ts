import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { UNITS, unitFor } from './units';
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
  it('server_utilisation is unverified and shown without a unit (UQ-1)', () => {
    const info = unitFor('server_utilisation');
    expect(info?.source).toBe('unverified');
    expect(info?.unit).toBeNull();
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
