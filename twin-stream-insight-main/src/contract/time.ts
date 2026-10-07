/**
 * FE-01: the only place timestamp strings are interpreted.
 *
 * Kinds (they are different clocks and must never be merged):
 *  - `sim`    the twin's own simulated clock. Offset-less by design. Labelled, NEVER converted to an instant.
 *  - `ingest` server wall clock (`ts_ingest`), documented as aware UTC. An offset-less value is a contract
 *             violation, not something to guess at.
 *  - `event`  / `alert`  backend timestamps that may be offset-less (naive UTC, debt D-2/BC-14). Offset-less
 *             input is assumed UTC and flagged with `offsetAssumed: true` so the UI can say so.
 *
 * Offset-less strings are never interpreted as browser-local time. Browser time is never data time.
 */

export type InstantKind = 'sim' | 'ingest' | 'event' | 'alert';

export type ParsedInstant =
  | {
      ok: true;
      kind: 'sim';
      /** Always labelled as the simulated clock. */
      clock: 'simulated';
      /** The original text, untouched. */
      text: string;
      instant: null;
      offsetAssumed: false;
    }
  | {
      ok: true;
      kind: 'ingest' | 'event' | 'alert';
      instant: Date;
      epochMs: number;
      /** true when the input had no offset and UTC was assumed (event/alert only). */
      offsetAssumed: boolean;
    }
  | {
      ok: false;
      kind: InstantKind;
      reason: 'empty' | 'malformed' | 'offset-required';
    };

const ISO =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?(Z|z|[+-]\d{2}(?::?\d{2})?)?$/;

export function parseInstant(input: unknown, kind: InstantKind): ParsedInstant {
  if (typeof input !== 'string' || input.trim() === '') return { ok: false, kind, reason: 'empty' };
  const text = input.trim();
  const m = ISO.exec(text);
  if (!m) return { ok: false, kind, reason: 'malformed' };

  const [, ys, mos, ds, hs, mis, ss, frac, off] = m;
  const year = Number(ys);
  const month = Number(mos);
  const day = Number(ds);
  const hour = Number(hs);
  const minute = Number(mis);
  const second = ss === undefined ? 0 : Number(ss);
  const ms = frac === undefined ? 0 : Number(frac.padEnd(3, '0').slice(0, 3));

  // Calendar validity: round-trip through Date.UTC so 2026-02-30 and 24:00 are rejected, not rolled over.
  const probe = new Date(Date.UTC(year, month - 1, day, hour, minute, second, ms));
  if (
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    return { ok: false, kind, reason: 'malformed' };
  }

  let offsetMin = 0;
  let offsetAssumed = false;
  if (off !== undefined && off.toUpperCase() !== 'Z') {
    const sign = off[0] === '-' ? -1 : 1;
    const digits = off.slice(1).replace(':', '');
    const oh = Number(digits.slice(0, 2));
    const om = digits.length > 2 ? Number(digits.slice(2, 4)) : 0;
    if (oh > 23 || om > 59) return { ok: false, kind, reason: 'malformed' };
    offsetMin = sign * (oh * 60 + om);
  }

  if (kind === 'sim') {
    // Labelled, never converted -- even if an offset happens to be present.
    return { ok: true, kind: 'sim', clock: 'simulated', text, instant: null, offsetAssumed: false };
  }

  if (off === undefined) {
    if (kind === 'ingest') return { ok: false, kind, reason: 'offset-required' };
    offsetAssumed = true; // event | alert: assume UTC, and say so
  }

  const epochMs = probe.getTime() - offsetMin * 60_000;
  return { ok: true, kind, instant: new Date(epochMs), epochMs, offsetAssumed };
}
