/** Task 28: contract for `/api/maintenance/*` (api/plugins/maintenance.py). Shape only; values are never defaulted. */
import { z } from "zod";

const num = z.number().finite();
export const HEALTH_STATUSES = ["ok", "watch", "warning", "no_data"] as const;
export const ORDER_STATUSES = ["open", "in_progress", "done", "cancelled"] as const;
export const PRIORITIES = ["low", "medium", "high"] as const;

const Trend = z
  .object({
    slope_per_day: num,
    change_over_window: num,
    span_hours: num,
    drift_pct_of_range: num.nullable(),
    direction: z.enum(["up", "down", "flat"]),
  })
  .passthrough();

const Sensor = z
  .object({
    measurand: z.string(),
    external_id: z.string(),
    status: z.enum(HEALTH_STATUSES),
    reasons: z.array(z.string()),
    samples: z.number().int(),
    valid_samples: z.number().int(),
    invalid_share: num,
    unit: z.string(),
    latest: z.object({ t: z.string(), value: num }).nullable(),
    trend: Trend.nullable(),
    series: z.array(z.object({ t: z.string(), v: num })),
  })
  .passthrough();

const RemainingLife = z.object({ available: z.boolean(), reason: z.string() }).passthrough();

const Asset = z
  .object({
    asset_id: z.number().int(),
    external_id: z.string(),
    name: z.string(),
    asset_type: z.string(),
    status: z.enum(HEALTH_STATUSES),
    sensor_count: z.number().int(),
    note: z.string().nullable(),
    sensors: z.array(Sensor),
    remaining_life: RemainingLife,
  })
  .passthrough();

export const HealthSchema = z
  .object({
    label: z.string(),
    origin: z.string(),
    window_hours: z.number().int(),
    counts: z.object({ ok: z.number().int(), watch: z.number().int(), warning: z.number().int(), no_data: z.number().int() }),
    remaining_life: RemainingLife,
    assets: z.array(Asset),
  })
  .passthrough();
export type Health = z.output<typeof HealthSchema>;
export type HealthAsset = Health["assets"][number];
export type HealthSensor = HealthAsset["sensors"][number];

export const WorkOrderSchema = z
  .object({
    id: z.number().int(),
    created_at: z.string().nullable(),
    updated_at: z.string().nullable(),
    created_by: z.string(),
    title: z.string(),
    description: z.string().nullable(),
    priority: z.enum(PRIORITIES),
    status: z.enum(ORDER_STATUSES),
    assignee: z.string().nullable(),
    asset_external_id: z.string().nullable(),
    source_kind: z.enum(["manual", "alert", "health"]),
    source_ref: z.string().nullable(),
    origin: z.string(),
    next_statuses: z.array(z.enum(ORDER_STATUSES)),
    record_label: z.string(),
  })
  .passthrough();
export type WorkOrder = z.output<typeof WorkOrderSchema>;
export const WorkOrderListSchema = z.array(WorkOrderSchema);
