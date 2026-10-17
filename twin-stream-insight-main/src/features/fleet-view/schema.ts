/** Task 30: contract for `GET /api/fleet/sites` (api/plugins/fleet.py). Shape only; values are never defaulted. */
import { z } from "zod";

const num = z.number().finite();

export const SiteSchema = z
  .object({
    id: z.string().min(1),
    name: z.string(),
    climate: z.string(),
    inputs: z.object({ utilisation: num, outside_temp_C: num, water_stress: num }),
    pue: num,
    wue: num,
    cooling_mode: z.string(),
    total_power_kw: num,
    server_outlet_temp_C: num,
    carbon_gco2_per_step: num,
    alert_conditions: z.number().int().nonnegative(),
    alert_condition_names: z.array(z.string()),
    rank: z.object({ pue: z.number().int().positive(), carbon_gco2_per_step: z.number().int().positive(), alert_conditions: z.number().int().positive() }),
    rank_sum: z.number().int().positive(),
    overall_rank: z.number().int().positive(),
  })
  .passthrough();

export const FleetSchema = z
  .object({
    simulated: z.literal(true),
    label: z.string(),
    alert_note: z.string(),
    carbon_data_is_real: z.boolean(),
    carbon_note: z.string(),
    carbon_unit: z.string(),
    sites: z.array(SiteSchema),
  })
  .passthrough();

export type Site = z.output<typeof SiteSchema>;
export type Fleet = z.output<typeof FleetSchema>;
