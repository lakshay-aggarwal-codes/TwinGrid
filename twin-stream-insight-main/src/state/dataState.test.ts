import { describe, it, expect } from 'vitest';
import { ApiError } from '@/api/apiError';
import { dataStateFromError, uiStateOf, STATE_VOCABULARY, type DataState } from './dataState';

describe('dataStateFromError', () => {
  it('maps unauthenticated to unauthorized/session_expired', () => {
    expect(dataStateFromError(new ApiError({ kind: 'unauthenticated', status: 401 }))).toEqual({
      status: 'unauthorized',
      reason: 'session_expired',
    });
  });

  it('maps forbidden to unauthorized/forbidden', () => {
    expect(dataStateFromError(new ApiError({ kind: 'forbidden', status: 403 }))).toEqual({
      status: 'unauthorized',
      reason: 'forbidden',
    });
  });

  it('keeps only kind and code for other ApiErrors', () => {
    expect(dataStateFromError(new ApiError({ kind: 'unavailable', status: 503, code: 'model_unavailable' }))).toEqual({
      status: 'error',
      kind: 'unavailable',
      code: 'model_unavailable',
    });
  });

  it('treats a non-ApiError as a generic server error and drops its message', () => {
    const state = dataStateFromError(new Error('SECRET backend detail'));
    expect(state).toEqual({ status: 'error', kind: 'server' });
    expect(JSON.stringify(state)).not.toContain('SECRET');
  });
});

describe('uiStateOf', () => {
  const err = (kind: 'unavailable' | 'contract' | 'network', code?: string): DataState<never> => ({ status: 'error', kind, code });

  it('distinguishes unavailable, unavailable_model and error', () => {
    expect(uiStateOf(err('unavailable'))).toBe('unavailable');
    expect(uiStateOf(err('contract'))).toBe('unavailable');
    expect(uiStateOf(err('unavailable', 'model_unavailable'))).toBe('unavailable_model');
    expect(uiStateOf(err('network'))).toBe('error');
  });

  it('keeps empty, not_run and loading distinct', () => {
    expect(uiStateOf({ status: 'empty' })).toBe('empty');
    expect(uiStateOf({ status: 'not_run' })).toBe('not_run');
    expect(uiStateOf({ status: 'loading' })).toBe('loading');
    expect(uiStateOf({ status: 'ready', data: 1 })).toBe('ready');
  });
});

describe('STATE_VOCABULARY roles (§11.1)', () => {
  it('matches the roadmap table', () => {
    expect(STATE_VOCABULARY.loading.role).toBe('status');
    expect(STATE_VOCABULARY.empty.role).toBeNull();
    expect(STATE_VOCABULARY.not_run.role).toBeNull();
    expect(STATE_VOCABULARY.error.role).toBe('alert');
    expect(STATE_VOCABULARY.unauthorized.role).toBe('alert');
    expect(STATE_VOCABULARY.stale.role).toBe('status');
    expect(STATE_VOCABULARY.disconnected.role).toBe('status');
    expect(STATE_VOCABULARY.disconnected.assertive).toBe(true);
    expect(STATE_VOCABULARY.unavailable.role).toBe('alert');
    expect(STATE_VOCABULARY.incomplete.role).toBeNull();
    expect(STATE_VOCABULARY.unsupported_scenario.role).toBe('status');
    expect(STATE_VOCABULARY.unavailable_model.role).toBe('status');
  });
});
