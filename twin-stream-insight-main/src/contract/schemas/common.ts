/**
 * Shared schema primitives.
 *
 * Rules enforced here (FE-01):
 *  - no `.default(...)`: a missing value stays missing; it is never turned into 0/''/false;
 *  - unknown extra object fields are tolerated (backend additions are additive);
 *  - enums never throw on an unrecognised value: they become a branded `Unknown` carrying the raw string.
 */
import { z } from 'zod';

declare const unknownBrand: unique symbol;

/** A backend vocabulary value this frontend does not recognise. Preserved verbatim, never coerced. */
export interface Unknown {
  readonly [unknownBrand]: true;
  readonly value: string;
}

export function makeUnknown(value: string): Unknown {
  return { value } as unknown as Unknown;
}

export function isUnknown(x: unknown): x is Unknown {
  return typeof x === 'object' && x !== null && 'value' in x && typeof (x as { value: unknown }).value === 'string';
}

/** `z.enum([...]).or(z.string())` where the fallback branch yields `Unknown`. Non-strings still fail. */
export function lenientEnum<const V extends readonly [string, ...string[]]>(values: V) {
  return z.enum(values).or(z.string().transform((s): Unknown => makeUnknown(s)));
}

/** Finite JSON number. Required unless the caller adds `.optional()`/`.nullable()`. */
export const num = z.number().finite();

/** Timestamps stay strings at the schema layer; interpret them only through `time.ts`. */
export const isoString = z.string().min(1);
