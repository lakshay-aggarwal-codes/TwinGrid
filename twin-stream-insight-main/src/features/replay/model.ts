/**
 * Task 14: replay state machine. PURE: no React, no clock, no network.
 *
 * Replay is a cursor over a requested window of STORED telemetry. It never writes anything and never claims to be live:
 * `mode: "live"` means "not replaying" (the page then shows the live feed's own freshness), every other mode means the
 * numbers on screen come from stored samples and the "REPLAY — not live" banner must be visible.
 *
 * Speed: 1x = one second of data time per second of wall time.
 */
export const SPEEDS = [1, 2, 5, 10, 30, 60] as const;
export type Speed = (typeof SPEEDS)[number];
export const DEFAULT_SPEED: Speed = 10;

/** The backend caps a query at 168 h (`TELEMETRY_MAX_SPAN_H`). */
export const WINDOW_HOURS = [1, 6, 24, 72, 168] as const;
export const DEFAULT_WINDOW_HOURS = 6;
export const MAX_WINDOW_HOURS = 168;

export type ReplayMode = "live" | "paused" | "playing";

export interface ReplayState {
  readonly mode: ReplayMode;
  /** Data time (epoch ms, UTC) the replay shows. null while live. */
  readonly cursorMs: number | null;
  readonly speed: Speed;
  /** Requested window, epoch ms. */
  readonly fromMs: number;
  readonly toMs: number;
  readonly compareOn: boolean;
  /** Compare time B (A is the cursor). null until chosen. */
  readonly compareBMs: number | null;
}

export type ReplayAction =
  | { type: "scrub"; ms: number }
  | { type: "play" }
  | { type: "pause" }
  | { type: "toggle" }
  | { type: "speed"; speed: number }
  | { type: "live" }
  | { type: "tick"; wallDeltaMs: number }
  | { type: "window"; fromMs: number; toMs: number }
  | { type: "compare"; on: boolean }
  | { type: "setB"; ms: number | null };

export const isSpeed = (n: unknown): n is Speed => SPEEDS.includes(n as Speed);

export const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/** True while the screen shows stored samples instead of the live feed (the banner is shown exactly then). */
export const isReplaying = (s: Pick<ReplayState, "mode">): boolean => s.mode !== "live";

export function initialState(window: { fromMs: number; toMs: number }, over: Partial<ReplayState> = {}): ReplayState {
  return { mode: "live", cursorMs: null, speed: DEFAULT_SPEED, fromMs: window.fromMs, toMs: window.toMs, compareOn: false, compareBMs: null, ...over };
}

export function replayReducer(s: ReplayState, a: ReplayAction): ReplayState {
  switch (a.type) {
    case "scrub": {
      if (!Number.isFinite(a.ms)) return s;
      // Scrubbing always leaves live. It pauses a running replay (the person took the handle).
      return { ...s, mode: "paused", cursorMs: clamp(a.ms, s.fromMs, s.toMs) };
    }
    case "play": {
      if (s.toMs <= s.fromMs) return s;
      // From live, or from the very end, start at the beginning of the window.
      const start = s.cursorMs === null || s.cursorMs >= s.toMs ? s.fromMs : s.cursorMs;
      return { ...s, mode: "playing", cursorMs: start };
    }
    case "pause":
      return s.mode === "playing" ? { ...s, mode: "paused" } : s;
    case "toggle":
      return replayReducer(s, { type: s.mode === "playing" ? "pause" : "play" });
    case "speed":
      return isSpeed(a.speed) ? { ...s, speed: a.speed } : s;
    case "live":
      return { ...s, mode: "live", cursorMs: null };
    case "tick": {
      if (s.mode !== "playing" || s.cursorMs === null || !(a.wallDeltaMs > 0)) return s;
      // A long frame (background tab) must not teleport the cursor: at most 1 s of wall time per tick.
      const next = s.cursorMs + Math.min(a.wallDeltaMs, 1000) * s.speed;
      return next >= s.toMs ? { ...s, mode: "paused", cursorMs: s.toMs } : { ...s, cursorMs: next };
    }
    case "window": {
      if (!Number.isFinite(a.fromMs) || !Number.isFinite(a.toMs) || a.toMs <= a.fromMs) return s;
      const cursorMs = s.cursorMs === null ? null : clamp(s.cursorMs, a.fromMs, a.toMs);
      const compareBMs = s.compareBMs === null ? null : clamp(s.compareBMs, a.fromMs, a.toMs);
      return { ...s, fromMs: a.fromMs, toMs: a.toMs, cursorMs, compareBMs };
    }
    case "compare":
      return { ...s, compareOn: a.on };
    case "setB":
      return { ...s, compareBMs: a.ms === null || !Number.isFinite(a.ms) ? null : clamp(a.ms, s.fromMs, s.toMs) };
    default:
      return s;
  }
}

/**
 * The requested window for a person who opened `?t=<tMs>` (or the latest window when `tMs` is null).
 * It ends at "now" unless that would leave `t` in the last quarter-window, in which case it is centred on `t`
 * (never past `nowMs`: stored telemetry does not exist in the future). Whole seconds.
 */
export function windowFor(tMs: number | null, hours: number, nowMs: number): { fromMs: number; toMs: number } {
  const h = clamp(Math.round(hours), 1, MAX_WINDOW_HOURS);
  const span = h * 3_600_000;
  const now = Math.floor(nowMs / 1000) * 1000;
  let toMs = now;
  if (tMs !== null && Number.isFinite(tMs)) toMs = Math.min(now, Math.floor((tMs + span / 2) / 1000) * 1000);
  return { fromMs: toMs - span, toMs };
}

/** Fraction 0..1 of `ms` along the window (clamped). A zero-length window is 0. */
export function fractionOf(ms: number, fromMs: number, toMs: number): number {
  return toMs <= fromMs ? 0 : clamp((ms - fromMs) / (toMs - fromMs), 0, 1);
}

export function msAtFraction(f: number, fromMs: number, toMs: number): number {
  return Math.round(fromMs + clamp(f, 0, 1) * (toMs - fromMs));
}

/** Keyboard step for the scrubber: Arrow = 1/100 of the window, Page = 1/10, Home/End = the ends. Null = not a scrub key. */
export function scrubKeyTarget(key: string, cursorMs: number, fromMs: number, toMs: number): number | null {
  const span = toMs - fromMs;
  switch (key) {
    case "ArrowLeft":
    case "ArrowDown":
      return clamp(cursorMs - span / 100, fromMs, toMs);
    case "ArrowRight":
    case "ArrowUp":
      return clamp(cursorMs + span / 100, fromMs, toMs);
    case "PageDown":
      return clamp(cursorMs - span / 10, fromMs, toMs);
    case "PageUp":
      return clamp(cursorMs + span / 10, fromMs, toMs);
    case "Home":
      return fromMs;
    case "End":
      return toMs;
    default:
      return null;
  }
}
