/**
 * FE-03: the ONLY place user-facing text for failures lives.
 *
 * - `ERROR_COPY` is keyed by `ApiErrorKind` with a `Record`, so adding a kind to `apiError.ts` without adding
 *   copy here fails typecheck, and `errorCopyFor` rejects any kind that is not an `ApiErrorKind`.
 * - Nothing here (or in the components that use it) reads `Error.message`, a backend `detail`, a stack or a body.
 * - Wording is deliberately generic; features own specific wording later.
 */
import type { ApiErrorKind } from '@/api/apiError';
import type { UiStateKind, UnauthorizedReason } from './dataState';

export interface StateCopy {
  readonly title: string;
  readonly description: string;
}

export interface ErrorCopy extends StateCopy {
  /** Whether "Try again" is a sensible action for this kind. */
  readonly retryable: boolean;
}

export const ERROR_COPY: Record<ApiErrorKind, ErrorCopy> = {
  unauthenticated: { title: 'Signed out', description: 'Your session has ended. Sign in again to continue.', retryable: false },
  forbidden: { title: 'No permission', description: 'Your account does not have permission to do this.', retryable: false },
  not_found: { title: 'Not found', description: 'The requested item was not found.', retryable: false },
  conflict: { title: 'Conflict', description: 'The request conflicts with the current state. Refresh and try again.', retryable: true },
  rate_limited: { title: 'Too many requests', description: 'Too many requests were sent. Wait a moment, then try again.', retryable: true },
  validation: { title: 'Request not accepted', description: 'The request was not accepted. Check the inputs and try again.', retryable: false },
  unavailable: { title: 'Service unavailable', description: 'The service is unavailable right now. Try again later.', retryable: true },
  server: { title: 'Something went wrong', description: 'The server could not complete the request.', retryable: true },
  network: { title: 'Could not reach the server', description: 'The server could not be reached. Check your connection.', retryable: true },
  contract: {
    title: 'Response not usable',
    description: 'The server sent a response this app cannot use. Reloading may help; if it persists, report it.',
    retryable: false,
  },
};

/** Rejects (at compile time) anything that is not an `ApiErrorKind`; exhaustive by construction. */
export function errorCopyFor(kind: ApiErrorKind): ErrorCopy {
  return ERROR_COPY[kind];
}

export const UNAUTHORIZED_COPY: Record<UnauthorizedReason, StateCopy> = {
  session_expired: { title: 'Signed out', description: 'Your session has ended. Sign in again to continue.' },
  forbidden: { title: 'No permission', description: 'Your account does not have permission to view or do this.' },
};

/** Generic default text per vocabulary state. `error`/`unauthorized` are refined by the two tables above. */
export const STATE_COPY: Record<UiStateKind, StateCopy> = {
  loading: { title: 'Loading', description: 'Loading…' },
  empty: { title: 'No items', description: 'Nothing to show yet.' },
  not_run: { title: 'Not run', description: 'This has not been run yet.' },
  error: { title: 'Something went wrong', description: 'The request failed.' },
  unauthorized: { title: 'Not authorised', description: 'You are not authorised to view this.' },
  stale: { title: 'Stale', description: 'This data is out of date.' },
  disconnected: { title: 'Disconnected', description: 'The connection to the server is down. Data shown may be out of date.' },
  unavailable: { title: 'Unavailable', description: 'The service is unavailable right now.' },
  incomplete: { title: 'Incomplete', description: 'Some values were not reported.' },
  unsupported_scenario: { title: 'Scenario not supported', description: 'This app does not support this scenario type.' },
  unavailable_model: { title: 'Model unavailable', description: 'No valid model is available right now.' },
};

export const STALE_REFRESH_FAILED_LABEL = 'Stale result — refresh failed';

export const RENDER_ERROR_COPY: StateCopy = {
  title: 'This view failed to display',
  description: 'Something went wrong while displaying this view. The problem has been reported.',
};
