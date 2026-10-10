import { describe, expect, it } from 'vitest';
import { FacilityIdSchema, TelemetryGapsSchema, TelemetrySamplesSchema } from './schema';
import { CAPTURED_EMPTY, CAPTURED_GAPS, CAPTURED_PAGE_1, CAPTURED_REPLAY, CAPTURED_SAMPLES_ANY, CAPTURED_SAMPLES_OK, clone } from './testFixtures';

describe('G-HIST captures parse', () => {
  it.each([
    ['ok', CAPTURED_SAMPLES_OK],
    ['any-with-invalid', CAPTURED_SAMPLES_ANY],
    ['empty window', CAPTURED_EMPTY],
    ['page 1 (has a cursor)', CAPTURED_PAGE_1],
    ['replay stream', CAPTURED_REPLAY],
  ])('samples: %s', (_n, fx) => {
    expect(TelemetrySamplesSchema.safeParse(fx).success).toBe(true);
  });

  it('gaps', () => expect(TelemetryGapsSchema.safeParse(CAPTURED_GAPS).success).toBe(true));
  it('empty window is items: [] (not an error)', () => expect(CAPTURED_EMPTY.items).toEqual([]));
  it('the last page has a null cursor, a middle page a string', () => {
    expect(typeof CAPTURED_PAGE_1.next_cursor).toBe('string');
    expect(CAPTURED_SAMPLES_ANY.next_cursor).toBeNull();
  });
});

describe('contract violations are refused, not repaired', () => {
  it('a null value is not a sample (a missing point is an absence)', () => {
    const bad = clone(CAPTURED_SAMPLES_ANY);
    (bad.items[0] as { value: unknown }).value = null;
    expect(TelemetrySamplesSchema.safeParse(bad).success).toBe(false);
  });
  it('a non-finite value is refused', () => {
    const bad = clone(CAPTURED_SAMPLES_ANY);
    (bad.items[0] as { value: unknown }).value = 'NaN';
    expect(TelemetrySamplesSchema.safeParse(bad).success).toBe(false);
  });
  it('a missing cursor key is refused (null is the documented last page)', () => {
    const bad: Record<string, unknown> = { ...clone(CAPTURED_SAMPLES_ANY) };
    delete bad.next_cursor;
    expect(TelemetrySamplesSchema.safeParse(bad).success).toBe(false);
  });
  it('unknown vocabulary survives as a string', () => {
    const odd = clone(CAPTURED_SAMPLES_ANY);
    Object.assign(odd.items[0], { origin: 'teleported', quality: 'sparkly', invalid_reason: 'cosmic-ray' });
    const parsed = TelemetrySamplesSchema.parse(odd);
    expect(parsed.items[0]).toMatchObject({ origin: 'teleported', quality: 'sparkly', invalid_reason: 'cosmic-ray' });
  });
  it('facility id must be a positive integer', () => {
    expect(FacilityIdSchema.safeParse({ id: 1, name: 'x' }).success).toBe(true);
    expect(FacilityIdSchema.safeParse({ id: 0 }).success).toBe(false);
    expect(FacilityIdSchema.safeParse({ id: '1' }).success).toBe(false);
  });
});
