/**
 * Task 27: contract for `GET /api/carbon/schedule` (api/plugins/carbon_schedule.py). Shape only; values are never
 * defaulted. A body that claims a window or a saving while its status says there is none is a contract violation
 * (so a screen can never show a fake saving because of a backend slip).
 */
import { z } from "zod";

const num = z.number().finite();
const int = z.number().int();

const windowSchema = z.object({ start_hour: int, end_hour: int, mean_gco2_per_kwh: num, emissions_kg: num }).passthrough();
const baselineSchema = z
  .object({
    kind: z.enum(["average_of_allowed_windows", "reference_start"]),
    start_hour: int.nullable(),
    end_hour: int.nullable(),
    mean_gco2_per_kwh: num,
    emissions_kg: num,
  })
  .passthrough();

export const STATUSES = ["ok", "no_variation", "unverified", "synthetic_demo"] as const;
export type ScheduleStatus = (typeof STATUSES)[number];

export const CarbonScheduleSchema = z
  .object({
    label: z.string(),
    basis: z.string(),
    profile: z.enum(["data", "synthetic_demo"]),
    status: z.enum(STATUSES),
    headline: z.string(),
    message: z.string(),
    synthetic_label: z.string().nullable(),
    site_timezone: z.string(),
    inputs: z.object({ duration_h: int, load_kw: num, window_start: int, window_hours: int, reference_start_hour: int.nullable() }).passthrough(),
    carbon: z.object({ is_fallback: z.boolean(), semantic: z.string(), statement: z.string(), time_varying_signal: z.boolean() }).passthrough(),
    curve_gco2_per_kwh: z.array(num).length(24).nullable(),
    best: windowSchema.nullable(),
    worst: windowSchema.nullable(),
    baseline: baselineSchema.nullable(),
    savings: z.object({ emissions_kg: num, pct: num.nullable() }).passthrough().nullable(),
    caveats: z.array(z.string()),
  })
  .passthrough()
  .superRefine((b, ctx) => {
    const claims = b.best !== null || b.savings !== null || b.baseline !== null;
    const mayClaim = b.status === "ok" || b.status === "synthetic_demo";
    if (claims && !mayClaim) ctx.addIssue({ code: "custom", message: "window or saving claimed without a supporting status" });
    if (mayClaim && (b.best === null || b.savings === null || b.baseline === null)) ctx.addIssue({ code: "custom", message: "status needs a window, baseline and saving" });
    if (b.status === "synthetic_demo" && (b.synthetic_label === null || b.profile !== "synthetic_demo")) ctx.addIssue({ code: "custom", message: "synthetic result must be labelled synthetic" });
    if (b.status !== "synthetic_demo" && b.synthetic_label !== null) ctx.addIssue({ code: "custom", message: "only a synthetic result may carry the synthetic label" });
  });

export type CarbonSchedule = z.output<typeof CarbonScheduleSchema>;
