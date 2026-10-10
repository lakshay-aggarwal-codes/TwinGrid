/**
 * FE-18 test fixtures.
 *
 * REAL SHAPE: `fixtures/*.json` are the committed captures of the real backend router
 * (docs/frontend/contracts/G-HIST.capture-*.json). Their VALUES are synthetic test values (300.0, 999999): they prove
 * shape and vocabulary only and must never be presented as measurements.
 *
 * Everything named `SYNTHETIC_*` is built here for a behaviour the captures do not contain (an unrecognised quality,
 * a large series, offset-less times). It is not backend output.
 */
import type { TelemetryGaps, TelemetrySample, TelemetrySamplesPage } from './schema';

const modules = import.meta.glob('./fixtures/*.json', { eager: true, import: 'default' }) as Record<string, unknown>;
const get = <T,>(name: string) => modules[`./fixtures/${name}.json`] as T;

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

export const CAPTURED_SAMPLES_ANY = get<TelemetrySamplesPage>('samples-any-with-invalid');
export const CAPTURED_SAMPLES_OK = get<TelemetrySamplesPage>('samples-ok');
export const CAPTURED_EMPTY = get<TelemetrySamplesPage>('samples-empty-window');
export const CAPTURED_PAGE_1 = get<TelemetrySamplesPage>('samples-page1');
export const CAPTURED_PAGE_2 = get<TelemetrySamplesPage>('samples-page2');
export const CAPTURED_REPLAY = get<TelemetrySamplesPage>('samples-replay-stream');
export const CAPTURED_GAPS = get<TelemetryGaps>('gaps');

export const SENSOR_ID = 'fac1.it_power_kw';

/** SYNTHETIC: one sample with an arbitrary shape; `ts` is an RFC 3339 UTC string. */
export const SYNTHETIC_SAMPLE = (ts: string, value = 1, over: Partial<TelemetrySample> = {}): TelemetrySample => ({
  ts_event: ts,
  ts_ingest: ts,
  value,
  origin: 'simulated',
  stream_id: 'live',
  quality: 'ok',
  invalid_reason: null,
  ...over,
});

/** SYNTHETIC: `n` samples, 1 second apart from 2026-03-01T00:00:00Z, as one page. */
export function SYNTHETIC_PAGE(n: number, startIndex: number, nextCursor: string | null): TelemetrySamplesPage {
  const base = Date.UTC(2026, 2, 1);
  const items = Array.from({ length: n }, (_, i) => {
    const iso = new Date(base + (startIndex + i) * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');
    return SYNTHETIC_SAMPLE(iso, startIndex + i);
  });
  return { external_id: SENSOR_ID, unit: 'kW', sampling_interval_s: 300, stream: 'live', quality: 'any', items, next_cursor: nextCursor };
}
