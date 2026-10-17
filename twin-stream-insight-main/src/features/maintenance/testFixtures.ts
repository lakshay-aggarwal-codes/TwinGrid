/** Task 28 test fixtures: SYNTHETIC rows shaped like `/api/maintenance/*` (not measurements). */
import type { Health, HealthAsset, HealthSensor, WorkOrder } from "./schema";

export const REMAINING = { available: false, reason: "No validated remaining-life model applies. Trend only." };

export const sensor = (over: Partial<HealthSensor> = {}): HealthSensor => ({
  measurand: "it_power_kw",
  external_id: "fac1.it_power_kw",
  status: "warning",
  reasons: ["fitted trend moved 39% of the valid range over the window"],
  samples: 40,
  valid_samples: 40,
  invalid_share: 0,
  unit: "kW",
  latest: { t: "2026-10-01T12:00:00+00:00", value: 49 },
  trend: { slope_per_day: 288, change_over_window: 39, span_hours: 3.25, drift_pct_of_range: 39, direction: "up" },
  series: [
    { t: "2026-10-01T08:00:00+00:00", v: 10 },
    { t: "2026-10-01T10:00:00+00:00", v: 30 },
    { t: "2026-10-01T12:00:00+00:00", v: 49 },
  ],
  ...over,
});

export const plant = (over: Partial<HealthAsset> = {}): HealthAsset => ({
  asset_id: 1,
  external_id: "facility-level",
  name: "Facility level",
  asset_type: "facility",
  status: "warning",
  sensor_count: 1,
  note: null,
  sensors: [sensor()],
  remaining_life: REMAINING,
  ...over,
});

export const rack = (n: number): HealthAsset => ({
  asset_id: 100 + n,
  external_id: `rack-${n}`,
  name: `rack-${n}`,
  asset_type: "rack",
  status: "no_data",
  sensor_count: 0,
  note: "No sensor is attached to this asset: health is NOT MEASURED.",
  sensors: [],
  remaining_life: REMAINING,
});

export const health = (over: Partial<Health> = {}): Health => ({
  label: "rule-based indicator on simulated data; not a failure prediction",
  origin: "simulated",
  window_hours: 24,
  counts: { ok: 0, watch: 0, warning: 1, no_data: 2 },
  remaining_life: REMAINING,
  assets: [plant(), rack(1), rack(2)],
  ...over,
});

export const order = (over: Partial<WorkOrder> = {}): WorkOrder => ({
  id: 7,
  created_at: "2026-10-01T09:00:00+00:00",
  updated_at: "2026-10-01T09:00:00+00:00",
  created_by: "op1",
  title: "Check Facility level (it_power_kw): health warning",
  description: null,
  priority: "high",
  status: "open",
  assignee: null,
  asset_external_id: "facility-level",
  source_kind: "health",
  source_ref: "facility-level:it_power_kw",
  origin: "simulated",
  next_statuses: ["in_progress", "cancelled"],
  record_label: "A work order is a record only. TwinGrid dispatches nothing and changes no equipment.",
  ...over,
});
