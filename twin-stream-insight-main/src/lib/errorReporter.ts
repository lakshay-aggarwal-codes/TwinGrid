/**
 * Stage 15: one funnel for real runtime errors (API failures, WebSocket
 * problems, render errors, uncaught exceptions).
 *
 * Every report is written to the console AND, when VITE_ERROR_REPORT_URL is
 * configured, POSTed there as JSON so an operator can actually see it in
 * production -- browser consoles are not observability. With no URL set the
 * console is the only sink; this repo ships no receiving endpoint (see the
 * Stage 15 report), so a sink has to be provided at deploy time.
 *
 * Deliberately dependency-free and defensive: reporting must never throw or
 * loop, never include tokens/credentials, and is throttled so a flapping
 * WebSocket or a render loop can't flood the sink.
 */

export type ErrorLevel = 'warning' | 'error';

export interface ErrorReport {
  level: ErrorLevel;
  source: string;
  message: string;
  stack?: string;
  page: string;
  timestamp: string;
}

const REPORT_URL = (import.meta.env.VITE_ERROR_REPORT_URL as string | undefined)?.trim() ?? '';
const DEDUPE_WINDOW_MS = 30_000;
const MAX_REPORTS_PER_MINUTE = 20;
const MAX_TRACKED_KEYS = 200;

const lastSent = new Map<string, number>();
let minuteStart = 0;
let sentThisMinute = 0;

function toMessage(error: unknown): { message: string; stack?: string } {
  if (error instanceof Error) return { message: error.message, stack: error.stack };
  if (typeof error === 'string') return { message: error };
  try {
    // JSON.stringify returns undefined (not a string) for undefined/symbols/functions.
    return { message: JSON.stringify(error) ?? String(error) };
  } catch {
    return { message: String(error) };
  }
}

/** Pure + exported for tests: should this (source,message) be sent right now? */
export function shouldSend(key: string, now: number): boolean {
  if (now - minuteStart >= 60_000) {
    minuteStart = now;
    sentThisMinute = 0;
  }
  if (sentThisMinute >= MAX_REPORTS_PER_MINUTE) return false;
  const prev = lastSent.get(key);
  if (prev !== undefined && now - prev < DEDUPE_WINDOW_MS) return false;
  if (lastSent.size >= MAX_TRACKED_KEYS) lastSent.clear();
  lastSent.set(key, now);
  sentThisMinute += 1;
  return true;
}

/** Test helper: reset throttle state. */
export function resetReporterState(): void {
  lastSent.clear();
  minuteStart = 0;
  sentThisMinute = 0;
}

function send(report: ErrorReport): void {
  if (!REPORT_URL) return;
  try {
    const body = JSON.stringify(report);
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      // text/plain keeps this a CORS "simple" request (no preflight) so the
      // beacon works against a bare collector; the payload is still JSON.
      if (navigator.sendBeacon(REPORT_URL, new Blob([body], { type: 'text/plain' }))) return;
    }
    void fetch(REPORT_URL, { method: 'POST', body, keepalive: true, headers: { 'Content-Type': 'text/plain' } }).catch(() => {});
  } catch {
    /* reporting must never throw */
  }
}

export function reportError(source: string, error: unknown, level: ErrorLevel = 'error'): void {
  try {
    const { message, stack } = toMessage(error);
    const now = Date.now();
    // Console output is throttled by the same key so a reconnect loop doesn't
    // bury the console either.
    if (!shouldSend(`${source}|${message}`, now)) return;
    const report: ErrorReport = {
      level,
      source,
      message: message.slice(0, 500),
      stack: stack?.slice(0, 2000),
      page: typeof location !== 'undefined' ? location.pathname : '',
      timestamp: new Date(now).toISOString(),
    };
    (level === 'error' ? console.error : console.warn)(`[${source}]`, message);
    send(report);
  } catch {
    /* reporting must never throw */
  }
}

/** Installs global handlers for anything nothing else caught. Call once at startup. */
export function installGlobalErrorHandlers(): void {
  window.addEventListener('error', (event) => {
    reportError('window.onerror', event.error ?? event.message);
  });
  window.addEventListener('unhandledrejection', (event) => {
    reportError('unhandledrejection', event.reason);
  });
}
