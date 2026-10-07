/**
 * FE-02: WebSocket /ws/live transport.
 *
 * Close-code table (backend BC-03, api/routes/websocket_routes.py):
 *   4002  access token expired mid-session -> refresh and reconnect immediately (once per valid frame)
 *   4001  invalid/missing token            -> refresh once and retry; a second 4001 stops and surfaces `unauthenticated`
 *   4003  connection cap / 4005 rate limit -> exponential backoff
 *   4004  Origin not allowed               -> stop, permanent `forbidden_origin`
 *   1009  message too big                  -> stop (client bug)
 *   other (1006, ...)                      -> exponential backoff
 *
 * The backoff is reset ONLY when a frame passes the contract layer, never merely because the socket opened
 * (a cap rejection opens and then closes). An open socket is therefore not "live": consumers must still require a
 * fresh valid frame.
 */
import { reportError } from '@/lib/errorReporter.ts';
import { AuthRequiredError, forceRefresh, getToken } from '../authClient';
import { API_BASE_URL, WS_LIVE_URL } from '../config';
import { LiveFrame, isSuccess, parseApi } from '../contract';
import { toLiveState, type LiveStatePayload } from './models';

const DEFAULT_RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 30000;
/** Probe /healthz once this many consecutive reconnect attempts have failed without a valid frame. */
const PROBE_AFTER_ATTEMPTS = 2;

/** Legacy coarse socket status kept for existing consumers (`useSimulation`, `liveness`). */
export type SocketStatus = 'connecting' | 'open' | 'closed';

export type TransportStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';
export type TransportClosedReason = 'client_disconnect' | 'unauthenticated' | 'forbidden_origin' | 'message_too_large';
/** Result of the unauthenticated /healthz probe. */
export type BackendProbe = 'unknown' | 'reachable' | 'unavailable' | 'unreachable';

export interface TransportState {
  status: TransportStatus;
  /** Set only when status is `closed`. */
  reason: TransportClosedReason | null;
  lastCloseCode: number | null;
  /** Consecutive failed attempts since the last valid frame. */
  attempt: number;
  /** Browser epoch ms of the scheduled retry (receipt-side scheduling, not data time). */
  nextRetryAt: number | null;
  backend: BackendProbe;
}

export interface WsConnection {
  disconnect: () => void;
  getState: () => TransportState;
}

/**
 * BC-15: the unauthenticated liveness probe. 503 -> `unavailable`. `/api/health` is JWT-protected and always
 * says "healthy" when reachable, so it is not a liveness probe.
 */
export async function probeHealthz(signal?: AbortSignal): Promise<BackendProbe> {
  try {
    const response = await fetch(new URL('/healthz', API_BASE_URL).toString(), { signal, cache: 'no-store' });
    if (response.ok) return 'reachable';
    if (response.status >= 500) return 'unavailable'; // 503 from the backend, 502/504 from a gateway
    return 'unknown'; // e.g. 404: the probe route itself is gone, which says nothing about the backend
  } catch {
    return 'unreachable';
  }
}

export function connectWebSocket(
  onMessage: (state: LiveStatePayload) => void,
  onStatus?: (status: SocketStatus) => void,
  onTransport?: (state: TransportState) => void
): WsConnection {
  let ws: WebSocket | null = null;
  let stopped = false;
  let delay = DEFAULT_RECONNECT_DELAY_MS;
  let timer: ReturnType<typeof setTimeout> | null = null;
  /** A refresh-and-reconnect was already spent since the last valid frame (4001/4002 guard against loops). */
  let refreshSpent = false;
  let probeAbort: AbortController | null = null;
  let state: TransportState = {
    status: 'connecting',
    reason: null,
    lastCloseCode: null,
    attempt: 0,
    nextRetryAt: null,
    backend: 'unknown',
  };

  function setState(patch: Partial<TransportState>): void {
    state = { ...state, ...patch };
    onTransport?.(state);
  }

  function stop(reason: TransportClosedReason): void {
    stopped = true;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    probeAbort?.abort();
    setState({ status: 'closed', reason, nextRetryAt: null });
  }

  async function probeBackend(): Promise<void> {
    if (probeAbort || stopped) return;
    probeAbort = new AbortController();
    const mine = probeAbort;
    const result = await probeHealthz(mine.signal);
    if (probeAbort === mine) probeAbort = null;
    if (!stopped && !mine.signal.aborted) setState({ backend: result });
  }

  function scheduleReconnect(): void {
    if (stopped || timer) return;
    const wait = delay;
    delay = Math.min(delay * 1.5, MAX_RECONNECT_DELAY_MS);
    const attempt = state.attempt + 1;
    setState({ status: 'reconnecting', attempt, nextRetryAt: Date.now() + wait });
    if (attempt >= PROBE_AFTER_ATTEMPTS) void probeBackend();
    timer = setTimeout(() => {
      timer = null;
      void connect();
    }, wait);
  }

  /** 4001/4002: one refresh, then reconnect immediately. Never loops without a valid frame in between. */
  async function refreshThenReconnect(code: 4001 | 4002): Promise<void> {
    if (refreshSpent) {
      if (code === 4001) {
        stop('unauthenticated');
        return;
      }
      scheduleReconnect(); // repeated 4002 (e.g. clock skew): back off instead of spinning
      return;
    }
    refreshSpent = true;
    setState({ status: 'reconnecting', nextRetryAt: null });
    try {
      await forceRefresh();
    } catch (e) {
      if (stopped) return;
      if (e instanceof AuthRequiredError) {
        stop('unauthenticated');
        return;
      }
      reportError('apiClient.websocket.refresh', e, 'warning');
      scheduleReconnect();
      return;
    }
    if (stopped) return;
    void connect();
  }

  function handleClose(code: number): void {
    onStatus?.('closed');
    setState({ lastCloseCode: code });
    switch (code) {
      case 4004:
        reportError('apiClient.websocket.closed', 'WebSocket closed (4004): origin not allowed', 'error');
        stop('forbidden_origin');
        return;
      case 1009:
        reportError('apiClient.websocket.closed', 'WebSocket closed (1009): message too big', 'error');
        stop('message_too_large');
        return;
      case 4001:
      case 4002:
        void refreshThenReconnect(code);
        return;
      default:
        // 4003 / 4005 / abnormal closes: keep backing off.
        reportError('apiClient.websocket.closed', `WebSocket closed (code ${code}); reconnecting`, 'warning');
        scheduleReconnect();
    }
  }

  function handleFrame(data: unknown): void {
    if (typeof data !== 'string') {
      reportError('apiClient.websocket.parse', 'Non-text frame dropped', 'warning');
      return;
    }
    let json: unknown;
    try {
      json = JSON.parse(data);
    } catch {
      // Not reported with the parse error: its text can quote part of the payload.
      reportError('apiClient.websocket.parse', 'Frame is not valid JSON; dropped', 'warning');
      return;
    }
    const parsed = parseApi(LiveFrame, json, 'ws.live'); // an invalid frame is reported there and dropped here
    if (!isSuccess(parsed)) return;

    // First valid frame proves the server is streaming: only now do backoff and the refresh guard reset.
    delay = DEFAULT_RECONNECT_DELAY_MS;
    refreshSpent = false;
    if (state.attempt !== 0 || state.backend !== 'reachable') setState({ attempt: 0, backend: 'reachable' });
    onMessage(toLiveState(parsed.data));
  }

  async function connect(): Promise<void> {
    if (stopped) return;
    onStatus?.('connecting');
    if (state.status !== 'reconnecting') setState({ status: 'connecting' });
    let token: string;
    try {
      token = await getToken();
    } catch (e) {
      if (stopped) return;
      onStatus?.('closed');
      if (e instanceof AuthRequiredError) {
        stop('unauthenticated');
        return;
      }
      reportError('apiClient.websocket.auth', e, 'warning');
      scheduleReconnect();
      return;
    }
    if (stopped) return;

    let sock: WebSocket;
    try {
      sock = new WebSocket(`${WS_LIVE_URL}?token=${encodeURIComponent(token)}`);
    } catch (e) {
      reportError('apiClient.websocket.construct', e, 'warning'); // errorReporter redacts `token=`
      onStatus?.('closed');
      scheduleReconnect();
      return;
    }
    ws = sock;

    sock.onmessage = (event) => {
      if (ws !== sock) return;
      handleFrame(event.data);
    };
    sock.onclose = (event) => {
      if (ws !== sock) return;
      ws = null;
      if (stopped) return;
      handleClose(event.code);
    };
    // The browser gives no detail on WebSocket errors; a close event always follows and is what gets handled.
    sock.onerror = () => {};
    sock.onopen = () => {
      if (ws !== sock) return;
      // Socket open only. Backoff is NOT reset here and the feed is not "live" until a valid frame arrives.
      setState({ status: 'open', nextRetryAt: null });
      onStatus?.('open');
    };
  }

  void connect();

  return {
    disconnect() {
      if (stopped) return;
      const sock = ws;
      ws = null;
      stop('client_disconnect');
      sock?.close();
    },
    getState: () => state,
  };
}
