import { describe, it, expect } from 'vitest';
import { ApiError, type ApiErrorKind } from '@/api/apiError';
import { ERROR_COPY, STATE_COPY, UNAUTHORIZED_COPY, errorCopyFor } from './errorCopy';
import { STATE_VOCABULARY } from './dataState';

// Type-level exhaustiveness: adding a kind to ApiErrorKind without listing it here fails typecheck.
const ALL_KINDS: Record<ApiErrorKind, true> = {
  unauthenticated: true,
  forbidden: true,
  not_found: true,
  conflict: true,
  rate_limited: true,
  validation: true,
  unavailable: true,
  server: true,
  network: true,
  contract: true,
};

describe('errorCopy', () => {
  it('has copy for exactly every ApiErrorKind (runtime mirror of the type-level check)', () => {
    expect(Object.keys(ERROR_COPY).sort()).toEqual(Object.keys(ALL_KINDS).sort());
  });

  it('every entry has non-empty title and description', () => {
    for (const kind of Object.keys(ALL_KINDS) as ApiErrorKind[]) {
      const copy = errorCopyFor(kind);
      expect(copy.title.length).toBeGreaterThan(0);
      expect(copy.description.length).toBeGreaterThan(0);
    }
  });

  it('an unknown ApiError.kind fails typecheck', () => {
    // @ts-expect-error 'bogus' is not an ApiErrorKind
    expect(() => errorCopyFor('bogus')).not.toThrow();
    // @ts-expect-error 'bogus' is not an ApiErrorKind
    expect(() => new ApiError({ kind: 'bogus' })).not.toThrow();
  });

  it('has copy for every vocabulary state and unauthorized reason', () => {
    expect(Object.keys(STATE_COPY).sort()).toEqual(Object.keys(STATE_VOCABULARY).sort());
    expect(Object.keys(UNAUTHORIZED_COPY).sort()).toEqual(['forbidden', 'session_expired']);
  });
});
