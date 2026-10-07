/**
 * FE-09: the optimisation run state machine (pure).
 *
 *   idle -> confirming -> submitting -> completed | failed{kind}
 *
 * There is no progress state: the backend sends none, so the UI only says "waiting for response". Any response
 * that arrives outside `submitting` (a stale one) is ignored.
 */
import { ApiError, type ApiErrorKind } from '@/api/apiError';
import { AuthRequiredError } from '@/authClient';
import type { OptimizeResponse } from '@/api/apiClient';

export type OptimizeRun =
  | { status: 'idle' }
  | { status: 'confirming' }
  | { status: 'submitting' }
  | { status: 'completed'; result: OptimizeResponse }
  | { status: 'failed'; kind: ApiErrorKind; code?: string; retryAfterS?: number };

export type OptimizeAction =
  | { type: 'request' }
  | { type: 'cancel' }
  | { type: 'submit' }
  | { type: 'succeeded'; result: OptimizeResponse }
  | { type: 'failed'; error: unknown }
  | { type: 'reset' };

export const INITIAL_RUN: OptimizeRun = { status: 'idle' };

export function failureOf(error: unknown): Extract<OptimizeRun, { status: 'failed' }> {
  if (error instanceof AuthRequiredError) return { status: 'failed', kind: 'unauthenticated' };
  if (error instanceof ApiError) {
    return {
      status: 'failed',
      kind: error.kind,
      ...(error.code !== undefined && { code: error.code }),
      ...(error.retryAfterS !== undefined && { retryAfterS: error.retryAfterS }),
    };
  }
  return { status: 'failed', kind: 'server' }; // an unknown thrown value: generic, its text is never kept
}

export function optimizeReducer(state: OptimizeRun, action: OptimizeAction): OptimizeRun {
  switch (action.type) {
    case 'request':
      return state.status === 'idle' || state.status === 'completed' || state.status === 'failed' ? { status: 'confirming' } : state;
    case 'cancel':
      return state.status === 'confirming' ? { status: 'idle' } : state;
    case 'submit':
      return state.status === 'confirming' ? { status: 'submitting' } : state;
    case 'succeeded':
      return state.status === 'submitting' ? { status: 'completed', result: action.result } : state;
    case 'failed':
      return state.status === 'submitting' ? failureOf(action.error) : state;
    case 'reset':
      return state.status === 'completed' || state.status === 'failed' ? { status: 'idle' } : state;
  }
}

/** The backend refused because it has no valid optimiser model (`503 model_unavailable`). Not a generic error. */
export function isModelUnavailable(run: Extract<OptimizeRun, { status: 'failed' }>): boolean {
  return run.kind === 'unavailable' && run.code === 'model_unavailable';
}

/** Optional response metadata, shown only when the backend sends it. */
export function optionalText(obj: object, key: string): string | null {
  if (!(key in obj)) return null;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === 'string' && v !== '' ? v : null;
}

export function optionalFlag(obj: object, key: string): boolean | null {
  if (!(key in obj)) return null;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === 'boolean' ? v : null;
}
