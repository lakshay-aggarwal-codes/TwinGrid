import { describe, expect, it } from 'vitest';
import { buildChartModel, buildSeries, distinctOrigins, qualityClass, requestWindow, sensorIdFor } from './model';
import { CAPTURED_GAPS, CAPTURED_SAMPLES_ANY, CAPTURED_SAMPLES_OK, SENSOR_ID, SYNTHETIC_SAMPLE, clone } from './testFixtures';

const build = (items = CAPTURED_SAMPLES_ANY.items, gaps = CAPTURED_GAPS.gaps) => buildSeries({ sensorId: SENSOR_ID, unit: 'kW', items, gaps });

describe('gaps are gaps', () => {
  it('inserts exactly one v:null break where the backend reports a gap, and nowhere else', () => {
    const { series } = build();
    const breaks = series.points.filter((p) => p.gapBreak);
    expect(breaks).toHaveLength(1);
    expect(breaks[0].v).toBeNull();
    expect(breaks[0].iso).toBe('2026-03-01T12:25:00Z'); // the gap start
    const i = series.points.indexOf(breaks[0]);
    expect(series.points[i - 1].iso).toBe('2026-03-01T12:25:00Z');
    expect(series.points[i + 1].iso).toBe('2026-03-01T12:50:00Z');
  });

  it('no gap reported => no break, even across a long hole (the client never infers a gap)', () => {
    const sparse = [SYNTHETIC_SAMPLE('2026-03-01T00:00:00Z'), SYNTHETIC_SAMPLE('2026-03-01T05:00:00Z')];
    expect(build(sparse, []).series.points.some((p) => p.gapBreak)).toBe(false);
  });

  it('null values appear only on breaks', () => {
    const { series } = build();
    expect(series.points.filter((p) => p.v === null).every((p) => p.gapBreak)).toBe(true);
  });

  it('chart model: the line carries the break, bands come from /gaps', () => {
    const { series } = build();
    const m = buildChartModel(series, CAPTURED_GAPS.gaps);
    expect(m.line.filter((p) => p.v === null)).toHaveLength(1);
    expect(m.gapBands).toHaveLength(1);
    expect(m.gapBands[0]).toMatchObject({ startIso: '2026-03-01T12:25:00Z', endIso: '2026-03-01T12:50:00Z', durationS: 1500 });
  });
});

describe('quality marks', () => {
  it('invalid samples are excluded from the line, listed, and keep the backend reason', () => {
    const { series } = build();
    const m = buildChartModel(series, CAPTURED_GAPS.gaps);
    expect(m.excluded).toHaveLength(1);
    expect(m.excluded[0]).toMatchObject({ quality: 'invalid', invalidReason: 'range', v: 999999 });
    expect(m.line.some((p) => p.v === 999999)).toBe(false);
    expect(m.goodCount).toBe(m.line.filter((p) => !p.gapBreak).length);
    expect(series.points.some((p) => p.quality === 'invalid')).toBe(true); // still in the series: listed
  });

  it('an unrecognised quality is not drawn as good', () => {
    expect(qualityClass('sparkly')).toBe('unrecognised');
    expect(qualityClass(null)).toBe('unrecognised');
    const { series } = build([SYNTHETIC_SAMPLE('2026-03-01T00:00:00Z', 1, { quality: 'sparkly' }), SYNTHETIC_SAMPLE('2026-03-01T00:05:00Z')], []);
    const m = buildChartModel(series, []);
    expect(m.excluded.map((p) => p.quality)).toEqual(['sparkly']);
    expect(m.goodCount).toBe(1);
  });

  it('an invalid sample between two valid ones does not itself break the line', () => {
    const items = [
      SYNTHETIC_SAMPLE('2026-03-01T00:00:00Z'),
      SYNTHETIC_SAMPLE('2026-03-01T00:01:00Z', 999, { quality: 'invalid', invalid_reason: 'range' }),
      SYNTHETIC_SAMPLE('2026-03-01T00:02:00Z'),
    ];
    const m = buildChartModel(build(items, []).series, []);
    expect(m.line.map((p) => p.v)).toEqual([1, 1]);
  });
});

describe('ordering and units', () => {
  it('does not re-sort: out-of-order points stay in the backend order and are counted', () => {
    const items = [SYNTHETIC_SAMPLE('2026-03-01T00:10:00Z', 1), SYNTHETIC_SAMPLE('2026-03-01T00:00:00Z', 2), SYNTHETIC_SAMPLE('2026-03-01T00:20:00Z', 3)];
    const built = build(items, []);
    expect(built.series.points.map((p) => p.v)).toEqual([1, 2, 3]);
    expect(built.orderViolations).toBe(1);
  });

  it('the captured samples are already ascending: zero violations', () => {
    expect(build().orderViolations).toBe(0);
    expect(build(CAPTURED_SAMPLES_OK.items).orderViolations).toBe(0);
  });

  it('an offset-less event time is refused (no zone is assumed)', () => {
    const built = build([SYNTHETIC_SAMPLE('2026-03-01T00:00:00'), SYNTHETIC_SAMPLE('2026-03-01T00:05:00Z')], []);
    expect(built.unreadable).toBe(1);
    expect(built.series.points).toHaveLength(1);
  });

  it('unit comes from the backend and is carried as given; absent stays null', () => {
    expect(build().series.unit).toBe('kW');
    expect(buildSeries({ sensorId: 'x', unit: undefined, items: [], gaps: [] }).series.unit).toBeNull();
  });

  it('origins are listed in first-seen order, null kept distinct', () => {
    const items = [SYNTHETIC_SAMPLE('2026-03-01T00:00:00Z', 1, { origin: 'replay' }), SYNTHETIC_SAMPLE('2026-03-01T00:01:00Z', 1, { origin: null }), SYNTHETIC_SAMPLE('2026-03-01T00:02:00Z', 1)];
    expect(distinctOrigins(build(items, []).series)).toEqual(['replay', null, 'simulated']);
  });
});

describe('request window', () => {
  it('is RFC 3339 UTC with Z, whole seconds, and exactly `hours` long', () => {
    const w = requestWindow(Date.UTC(2026, 2, 1, 12, 0, 0, 999), 24);
    expect(w.to).toBe('2026-03-01T12:00:00Z');
    expect(w.from).toBe('2026-02-28T12:00:00Z');
    expect(w.toMs - w.fromMs).toBe(24 * 3_600_000);
    expect(w.from).toMatch(/Z$/);
  });
  it('builds the default sensor id from the facility id', () => expect(sensorIdFor(1, 'it_power_kw')).toBe('fac1.it_power_kw'));
});
