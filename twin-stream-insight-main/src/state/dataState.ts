/**
 * FE-03: the one UI-state vocabulary (roadmap §11.1) and the `DataState<T>` union.
 *
 * Meanings live here once. Screens never hand-roll loading/empty/error: they hold a `DataState<T>` and
 * render it through `StateBoundary`, or render a single state with `StateNotice`.
 */
import { isApiError, type ApiErrorKind } from '@/api/apiError';

/** Every state the UI can show for a piece of data. `ready` is not a notice, so it is not in this list. */
export type UiStateKind =
  | 'loading'
  | 'empty'
  | 'not_run'
  | 'error'
  | 'unauthorized'
  | 'stale'
  | 'disconnected'
  | 'unavailable'
  | 'incomplete'
  | 'unsupported_scenario'
  | 'unavailable_model';

/** ARIA role per state. `null` = inline, no live-region role. */
export type StateRole = 'status' | 'alert' | null;

export interface StateVocabularyEntry {
  /** What the state means. */
  readonly meaning: string;
  /** What it must never be confused with (§11.1 "Never means"). */
  readonly neverMeans: string;
  readonly role: StateRole;
  /** `disconnected` is announced assertively, once, on the transition. */
  readonly assertive?: boolean;
}

export const STATE_VOCABULARY: Record<UiStateKind, StateVocabularyEntry> = {
  loading: { meaning: 'Request in flight, no data yet.', neverMeans: 'zero', role: 'status' },
  empty: { meaning: 'Request succeeded; the backend returned no items.', neverMeans: 'error', role: null },
  not_run: { meaning: 'An evaluation or run that has not been executed.', neverMeans: 'empty or failed', role: null },
  error: { meaning: 'Request failed; ApiError.kind selects the copy.', neverMeans: 'raw backend text', role: 'alert' },
  unauthorized: {
    meaning: '401 after refresh failure (sign in) or 403 (no permission).',
    neverMeans: 'try again forever',
    role: 'alert',
  },
  stale: { meaning: 'Data older than its freshness window.', neverMeans: 'current', role: 'status' },
  disconnected: { meaning: 'Transport is down.', neverMeans: 'backend down', role: 'status', assertive: true },
  unavailable: {
    meaning: 'Backend, model or engine down; invalid payload; or incompatible schema_version.',
    neverMeans: 'disconnected',
    role: 'alert',
  },
  incomplete: { meaning: 'Optional fields are missing (shown as "not reported").', neverMeans: 'hidden', role: null },
  unsupported_scenario: { meaning: 'Scenario kind not understood by this client.', neverMeans: 'selectable', role: 'status' },
  unavailable_model: {
    meaning: 'Backend reports no valid model (e.g. 503 model_unavailable).',
    neverMeans: 'error',
    role: 'status',
  },
};

/** Backend machine code (BC-13 interim) that distinguishes "no valid model" from a generic outage. */
export const MODEL_UNAVAILABLE_CODE = 'model_unavailable';

export type UnauthorizedReason = 'session_expired' | 'forbidden';

/** Coarse data freshness a screen may attach to `ready` data. FE-04 owns the feed freshness machine. */
export type DataFreshness = 'fresh' | 'stale' | 'disconnected';

export type DataState<T> =
  | { readonly status: 'loading' }
  | { readonly status: 'empty' }
  | { readonly status: 'not_run' }
  | { readonly status: 'error'; readonly kind: ApiErrorKind; readonly code?: string }
  | { readonly status: 'unauthorized'; readonly reason: UnauthorizedReason }
  | {
      readonly status: 'ready';
      readonly data: T;
      readonly freshness?: DataFreshness;
      /** Last-good data shown after a failed refetch. Always rendered with an explicit label. */
      readonly refreshFailed?: boolean;
      /** Labels of optional fields the backend did not report. Rendered as "not reported", never hidden. */
      readonly incomplete?: readonly string[];
    };

/** Map any thrown value to a `DataState`. Only `ApiError.kind` (and a short machine code) survives; message text is dropped. */
export function dataStateFromError(error: unknown): DataState<never> {
  if (isApiError(error)) {
    if (error.kind === 'unauthenticated') return { status: 'unauthorized', reason: 'session_expired' };
    if (error.kind === 'forbidden') return { status: 'unauthorized', reason: 'forbidden' };
    return { status: 'error', kind: error.kind, code: error.code };
  }
  // Anything that is not an ApiError escaped the transport layer: treat it as a generic server-side failure.
  return { status: 'error', kind: 'server' };
}

/** Which vocabulary entry a `DataState` renders as. `ready` renders its children (plus notices). */
export function uiStateOf<T>(state: DataState<T>): UiStateKind | 'ready' {
  switch (state.status) {
    case 'ready':
      return 'ready';
    case 'error':
      if (state.kind === 'unavailable') return state.code === MODEL_UNAVAILABLE_CODE ? 'unavailable_model' : 'unavailable';
      if (state.kind === 'contract') return 'unavailable';
      return 'error';
    default:
      return state.status;
  }
}
