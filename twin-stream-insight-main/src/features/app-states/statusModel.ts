import { classifyOrigin, type OriginState } from "@/provenance/model";
import { formatAge } from "@/provenance/labels";
import type { FreshnessState } from "@/telemetry/freshness";

export type ConnectionIcon = "live" | "connecting" | "stale" | "offline" | "unavailable";

export interface ConnectionView {
  state: FreshnessState;
  label: string;
  icon: ConnectionIcon;
  /** Disconnected and unavailable are announced assertively, once, on the transition (FE-03 vocabulary). */
  assertive: boolean;
}

/** A Record, so a new FreshnessState cannot be added without wording for it here. */
const CONNECTION: Record<FreshnessState, Omit<ConnectionView, "state">> = {
  connecting: { label: "Connecting", icon: "connecting", assertive: false },
  live: { label: "Live", icon: "live", assertive: false },
  stale: { label: "Stale", icon: "stale", assertive: false },
  disconnected: { label: "Disconnected", icon: "offline", assertive: true },
  reconnecting: { label: "Reconnecting", icon: "connecting", assertive: false },
  unavailable: { label: "Backend unavailable", icon: "unavailable", assertive: true },
};

export const connectionView = (state: FreshnessState): ConnectionView => ({ state, ...CONNECTION[state] });

/** "Last update: 4 s ago", or an explicit "No data received yet" -- never a blank or a 0. Age is browser receipt time, not data time. */
export function lastUpdateText(receivedAt: number | null, now: number): string {
  if (receivedAt === null) return "No data received yet";
  return `Last update: ${formatAge(Math.max(now - receivedAt, 0))}`;
}

export interface OriginChip {
  /** null until a frame has arrived: nothing is claimed about a source that has not been seen. */
  state: OriginState | null;
  text: string;
}

/** The origin is the backend's own word for it; absent or unrecognised is shown as "Unverified source", never as simulated. */
export function originChip(hasFrame: boolean, origin: unknown): OriginChip {
  if (!hasFrame) return { state: null, text: "Data origin: not reported yet" };
  const o = classifyOrigin(origin);
  return { state: o.state, text: `Data origin: ${o.text}` };
}
