/** FE-06 test helpers (test-only; never import from app code). Builds `LiveFeed` values for each freshness state. */
import type { LiveStatePayload } from "@/api/apiClient";
import type { Freshness, FreshnessState } from "@/telemetry/freshness";
import type { LiveFeed } from "./visualizationModes";

export function frameState(extra: Partial<LiveStatePayload> = {}): LiveStatePayload {
  return {
    timestamp: "2026-01-01T12:35:00",
    server_utilisation: 0.5,
    outside_temp_C: 22,
    server_inlet_temp_C: 20,
    server_outlet_temp_C: 30,
    it_power_kw: 300,
    cooling_power_kw: 60,
    total_power_kw: 360,
    pue: 1.23,
    water_flow_lpm: 10,
    water_consumed_L: 5,
    wue: 0.456,
    humidity_pct: 50,
    water_pressure_bar: 3,
    cooling_mode: "hybrid",
    anomaly: 0,
    ...extra,
  };
}

export function freshnessOf(state: FreshnessState, ageMs: number | null): Freshness {
  return { state, ageMs, staleAfterMs: 9000, lastReceivedAt: ageMs === null ? null : 1000 };
}

export interface FeedOptions {
  state?: Partial<LiveStatePayload>;
  /** Backend origin string; `null` = the frame carried no origin; omitted = "simulated". */
  origin?: string | null;
  ageMs?: number | null;
  withFrame?: boolean;
  attempt?: number | null;
}

/** A feed in `state`. Defaults: a frame with origin "simulated", age 0 for live and 42 s otherwise. */
export function feedIn(state: FreshnessState, o: FeedOptions = {}): LiveFeed {
  const ageMs = o.ageMs === undefined ? (state === "live" ? 500 : 42_000) : o.ageMs;
  const withFrame = o.withFrame ?? state !== "connecting";
  const freshness = freshnessOf(state, withFrame ? ageMs : null);
  return {
    frame: withFrame
      ? {
          value: frameState(o.state),
          provenance: {
            ...(o.origin === null ? {} : { origin: o.origin === undefined ? "simulated" : o.origin }),
            tsIngest: "2026-10-06T14:03:21Z",
            simTime: "2026-01-01T12:35:00",
            seq: 1,
          },
          freshness,
          receivedAt: 1000,
        }
      : null,
    freshness,
    reconnectAttempt: o.attempt ?? null,
  };
}
