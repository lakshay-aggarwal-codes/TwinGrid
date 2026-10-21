import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchRequestStatus, type AccessRequestStatus } from './api';
import type { AccessTicket } from './ticket';

export const POLL_INITIAL_MS = 5_000;
export const POLL_MAX_MS = 30_000;
/** Once a request is in one of these there is nothing more to wait for. `approved` keeps polling (it may become activated or expire). */
const STOP_POLLING = new Set(['activated', 'rejected', 'expired']);

export interface RequestStatusState {
  phase: 'loading' | 'ok' | 'not_found';
  data: AccessRequestStatus | null;
  /** The last check could not reach the server (or got an unusable answer). `data` is the last known status, if any. */
  offline: boolean;
}

/**
 * Polls GET /api/access-requests/{ref}/status. Starts at 5 s and backs off to 30 s while nothing changes (or while the
 * server cannot be reached); a status change, the tab becoming visible again, the browser coming back online, or
 * `checkNow()` all return to 5 s and check immediately. Nothing is requested while the tab is hidden.
 */
export function useRequestStatus(ticket: AccessTicket | null): RequestStatusState & { checkNow: () => void } {
  const [state, setState] = useState<RequestStatusState>({ phase: 'loading', data: null, offline: false });
  const checkRef = useRef<() => void>(() => undefined);
  const ref = ticket?.ref;
  const token = ticket?.token;

  useEffect(() => {
    if (!ref || !token) return undefined;
    let cancelled = false;
    let stopped = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = POLL_INITIAL_MS;
    let lastStatus: string | null = null;

    const clearTimer = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    };
    const schedule = () => {
      clearTimer();
      if (cancelled || stopped || document.hidden) return;
      timer = setTimeout(() => void run(), delay);
    };
    const run = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      clearTimer();
      const result = await fetchRequestStatus(ref, token);
      inFlight = false;
      if (cancelled) return;
      if (result.kind === 'ok') {
        delay = result.data.status === lastStatus ? Math.min(delay * 2, POLL_MAX_MS) : POLL_INITIAL_MS;
        lastStatus = result.data.status;
        stopped = STOP_POLLING.has(result.data.status);
        setState({ phase: 'ok', data: result.data, offline: false });
      } else if (result.kind === 'not_found') {
        stopped = true;
        setState({ phase: 'not_found', data: null, offline: false });
      } else {
        delay = Math.min(delay * 2, POLL_MAX_MS);
        setState((prev) => ({ ...prev, offline: true }));
      }
      schedule();
    };
    const checkNow = () => {
      if (stopped) return;
      delay = POLL_INITIAL_MS;
      void run();
    };
    checkRef.current = checkNow;

    const onVisibility = () => {
      if (document.hidden) clearTimer();
      else checkNow();
    };
    const onOffline = () => setState((prev) => ({ ...prev, offline: true }));
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('online', checkNow);
    window.addEventListener('offline', onOffline);

    // A request opened in a background tab waits until the tab is shown (onVisibility).
    if (!document.hidden) void run();

    return () => {
      cancelled = true;
      clearTimer();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('online', checkNow);
      window.removeEventListener('offline', onOffline);
    };
  }, [ref, token]);

  const checkNow = useCallback(() => checkRef.current(), []);
  return { ...state, checkNow };
}
