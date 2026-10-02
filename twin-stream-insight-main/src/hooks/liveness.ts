/**
 * Live-feed liveness and data-origin helpers (T1a).
 *
 * Liveness is derived ONLY from things the browser can observe itself: the
 * socket state and the wall-clock time at which the last payload was received.
 * It deliberately does NOT use the payload's `sim_time` (simulated clock, not
 * event time) and does not compare the server's `ts_ingest` with the client
 * clock (clock skew would make a healthy feed look stale).
 */

export type SocketStatus = "connecting" | "open" | "closed";
export type LivenessStatus = "connecting" | "live" | "stale" | "disconnected";

/** Nominal wall-seconds between payloads when the server does not say (pre-T1a backend). */
export const DEFAULT_INTERVAL_S = 3;
/** The feed is stale after this many missed intervals... */
export const STALE_INTERVAL_MULTIPLIER = 3;
/** ...but never sooner than this, so a fast interval cannot flap the indicator. */
export const MIN_STALE_AFTER_MS = 5000;
/** How often the hook re-evaluates liveness between payloads. */
export const LIVENESS_CHECK_INTERVAL_MS = 1000;

/** Stale window (ms) for a given payload `interval_s` (wall seconds between ticks). */
export function staleAfterMs(intervalS?: number | null): number {
  const s = typeof intervalS === "number" && Number.isFinite(intervalS) && intervalS > 0 ? intervalS : DEFAULT_INTERVAL_S;
  return Math.max(MIN_STALE_AFTER_MS, s * 1000 * STALE_INTERVAL_MULTIPLIER);
}

export interface LivenessInput {
  socket: SocketStatus;
  /** `Date.now()` when the last payload arrived; null if none yet. */
  lastMessageAt: number | null;
  now: number;
  staleAfterMs: number;
}

/**
 * - never received a payload: "connecting" until the socket has closed, then "disconnected"
 * - socket not open (closed, or re-connecting after an earlier payload): "disconnected"
 * - socket open but no payload for longer than the stale window: "stale"
 * - otherwise "live"
 */
export function deriveLiveness({ socket, lastMessageAt, now, staleAfterMs: windowMs }: LivenessInput): LivenessStatus {
  if (lastMessageAt === null) return socket === "closed" ? "disconnected" : "connecting";
  if (socket !== "open") return "disconnected";
  return now - lastMessageAt > windowMs ? "stale" : "live";
}

export type OriginTone = "simulated" | "unverified";

export interface OriginBanner {
  label: string;
  title: string;
  tone: OriginTone;
}

/**
 * Banner driven by the payload's own `origin`. Nothing here ever implies measured data:
 * only an explicit "simulated" is recognised; a missing or unrecognised origin is
 * shown as an unverified source.
 */
export function originBanner(origin: string | undefined | null): OriginBanner {
  if (origin === "simulated") {
    return {
      label: "Simulated",
      title:
        "Every value on this page comes from the physics simulator, not from measured telemetry. " +
        "Timestamps in the feed are simulated-clock time, not event time.",
      tone: "simulated",
    };
  }
  return {
    label: "Unverified source",
    title: "The data feed did not declare where its values come from, so they are not presented as measured.",
    tone: "unverified",
  };
}
