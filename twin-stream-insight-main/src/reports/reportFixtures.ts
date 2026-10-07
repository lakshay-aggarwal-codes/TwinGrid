/** FE-10 test support: deterministic captures/inputs for the report builders. Test-only; never import from app code. */
import type { AlertRecord, WhatIfResponse } from "@/api/apiClient";
import type { FreshnessState } from "@/telemetry/freshness";
import { feedIn } from "@/three/feedTestUtils";
import type { ReportCapture } from "./reports";

export const BROWSER_TIME = new Date("2026-10-06T15:00:00.000Z");

export const ANOMALY_STATUS = {
  status: "ok",
  message: "ok",
  score: 0.0123,
  threshold: 0.05,
  type: null,
  window_size: 30,
  window_filled: 30,
  detector_id: "ae-1",
  model_version: "v3",
  trained_on: "synthetic",
};

/** A feed in `state` plus the capture a report would take of it. Live payload: origin simulated, fallback carbon. */
export function captureIn(state: FreshnessState, extra: Record<string, unknown> = {}) {
  const feed = feedIn(state, {
    state: {
      origin: "simulated",
      ts_ingest: "2026-10-06T14:03:21Z",
      sim_time: "2026-01-01T12:35:00",
      anomaly_status: ANOMALY_STATUS,
      carbon_data_is_real: false,
      ...extra,
    } as never,
  });
  const capture: ReportCapture = { frame: feed.frame, freshness: feed.freshness, browserTime: BROWSER_TIME };
  return { feed, capture, liveState: feed.frame!.value };
}

export const WHATIF: WhatIfResponse = {
  hours: 24,
  basis: "constant inputs",
  mean_pue: 1.3,
  wue: 0.4,
  total_water_L: 1000,
  total_energy_kwh: 5000,
  total_co2_kg: 100,
  max_outlet_temp_C: 40,
  final_cooling_mode: "hybrid",
  drought_override_active: false,
  carbon_data_is_real: true,
};

export const CFG = { serverUtil: 65, outsideTemp: 22, waterStress: 0.4, chilledWaterSetpoint: 7, coolingMode: "Auto", aiOptimizer: true } as never;

export const ALERTS: AlertRecord[] = [
  { id: 1, created_at: "2026-10-06T10:00:00Z", type: "spike", message: "m1", severity: "WARNING", score: 0.1, alert: true, acknowledged: true, acknowledged_by: "alice", acknowledged_at: null, origin: "simulated", model_version: "v3" },
  { id: 2, created_at: null, type: "spike", message: "m2", severity: "CRITICAL", score: 0.2, alert: true, acknowledged: false, acknowledged_by: null, acknowledged_at: null },
];
