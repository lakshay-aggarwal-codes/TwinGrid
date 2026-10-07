/**
 * FE-04: `Stamped<T>` -- the only way feed values leave the store. A value never travels without the provenance
 * inputs it arrived with and the freshness at that moment, so "last known" cannot be shown without its age.
 */
import type { Freshness } from './freshness';

/**
 * Raw provenance fields exactly as the frame carried them (all optional: an older backend sends none; absent
 * origin must be shown as "Unverified source"). FE-05's `buildProvenance` consumes this; nothing is interpreted here.
 */
export interface ProvenanceInput {
  readonly origin?: string;
  readonly schemaVersion?: number;
  readonly seq?: number;
  readonly tsIngest?: string;
  readonly simTime?: string;
  readonly simTimeScale?: number;
  readonly intervalS?: number;
}

export interface Stamped<T> {
  readonly value: T;
  readonly provenance: ProvenanceInput;
  readonly freshness: Freshness;
  /** Monotonic receipt time (browser). Not data time. */
  readonly receivedAt: number;
}

/** True when the value must be rendered as "last known" (with `freshness.ageMs`), never in the live style. */
export function isLastKnown<T>(s: Stamped<T>): boolean {
  return s.freshness.state !== 'live';
}

/** Project a field of a stamped frame while keeping its provenance and freshness. */
export function stampedField<T, K extends keyof T>(s: Stamped<T>, key: K): Stamped<T[K]> {
  return { value: s.value[key], provenance: s.provenance, freshness: s.freshness, receivedAt: s.receivedAt };
}
