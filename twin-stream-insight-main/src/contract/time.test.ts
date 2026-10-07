import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { parseInstant } from './time';

describe('parseInstant', () => {
  describe('sim (simulated clock)', () => {
    it('labels an offset-less string as simulated and never converts it', () => {
      const r = parseInstant('2026-01-01T12:35:00', 'sim');
      expect(r).toEqual({ ok: true, kind: 'sim', clock: 'simulated', text: '2026-01-01T12:35:00', instant: null, offsetAssumed: false });
    });
    it('does not convert even when an offset is present', () => {
      const r = parseInstant('2026-01-01T12:35:00+05:30', 'sim');
      expect(r.ok && r.kind === 'sim' && r.instant).toBe(null);
    });
  });

  describe('ingest (server aware-UTC wall clock)', () => {
    it('accepts Z, +00:00 and numeric offsets', () => {
      const z = parseInstant('2026-10-06T10:00:00Z', 'ingest');
      const p = parseInstant('2026-10-06T10:00:00+00:00', 'ingest');
      const ist = parseInstant('2026-10-06T15:30:00+05:30', 'ingest');
      const compact = parseInstant('2026-10-06T05:00:00-0500', 'ingest');
      const expected = Date.UTC(2026, 9, 6, 10, 0, 0);
      for (const r of [z, p, ist, compact]) {
        expect(r.ok && r.kind === 'ingest' && r.epochMs).toBe(expected);
        expect(r.ok && r.kind === 'ingest' && r.offsetAssumed).toBe(false);
      }
    });
    it('keeps milliseconds and truncates python microseconds', () => {
      const r = parseInstant('2026-10-06T10:00:00.123456+00:00', 'ingest');
      expect(r.ok && r.kind === 'ingest' && r.epochMs).toBe(Date.UTC(2026, 9, 6, 10, 0, 0, 123));
    });
    it('rejects an offset-less value instead of guessing', () => {
      expect(parseInstant('2026-10-06T10:00:00', 'ingest')).toEqual({ ok: false, kind: 'ingest', reason: 'offset-required' });
    });
  });

  describe.each(['event', 'alert'] as const)('%s (offset-less allowed)', (kind) => {
    const prevTz = process.env.TZ;
    beforeAll(() => {
      process.env.TZ = 'Asia/Kolkata'; // a non-UTC local zone: local interpretation would change the result
    });
    afterAll(() => {
      if (prevTz === undefined) delete process.env.TZ;
      else process.env.TZ = prevTz;
    });

    it('assumes UTC (not browser-local) and flags offsetAssumed', () => {
      const r = parseInstant('2026-10-06T10:00:00', kind);
      expect(r.ok && r.kind !== 'sim' && r.epochMs).toBe(Date.UTC(2026, 9, 6, 10, 0, 0));
      expect(r.ok && r.kind !== 'sim' && r.offsetAssumed).toBe(true);
    });
    it('accepts python str(datetime) with a space separator', () => {
      const r = parseInstant('2026-10-06 10:00:00.5', kind);
      expect(r.ok && r.kind !== 'sim' && r.epochMs).toBe(Date.UTC(2026, 9, 6, 10, 0, 0, 500));
    });
    it('honours an explicit offset and does not flag it as assumed', () => {
      const r = parseInstant('2026-10-06T15:30:00+05:30', kind);
      expect(r.ok && r.kind !== 'sim' && r.epochMs).toBe(Date.UTC(2026, 9, 6, 10, 0, 0));
      expect(r.ok && r.kind !== 'sim' && r.offsetAssumed).toBe(false);
    });
  });

  describe('malformed input is rejected, never rolled over', () => {
    it.each([
      ['yesterday'],
      ['2026-01-01'], // date only: no time, not an instant
      ['2026-02-30T00:00:00Z'],
      ['2026-13-01T00:00:00Z'],
      ['2026-01-01T24:00:00Z'],
      ['2026-01-01T12:60:00Z'],
      ['2026-01-01T12:00:60Z'],
      ['2026-01-01T12:00:00+24:00'],
    ])('%s', (s) => {
      for (const kind of ['sim', 'ingest', 'event', 'alert'] as const) {
        const r = parseInstant(s, kind);
        expect(r.ok).toBe(false);
      }
    });
    it.each([[''], ['   '], [null], [undefined], [12345], [{}]])('non-string / empty %j', (v) => {
      expect(parseInstant(v, 'event')).toEqual({ ok: false, kind: 'event', reason: 'empty' });
    });
  });
});
