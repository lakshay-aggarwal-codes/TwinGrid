/** Task 26: contract for `GET /api/capacity/headroom` (api/plugins/capacity.py). Shape only; values are never defaulted. */
import { z } from "zod";

const num = z.number().finite();
const status = z.enum(["ok", "tight", "exceeded", "unknown"]);

const side = z
  .object({
    it_power_kw: num,
    cooling_power_kw: num,
    pue: num,
    max_outlet_temp_C: num,
    power_headroom_kw: num,
    power_limit_kw: num,
    cooling_headroom_kw: num.nullable(),
    cooling_capacity_kw: num.nullable(),
    thermal_margin_C: num,
    inlet_margin_C: num,
    status: z.object({ power: status, cooling: status, thermal: status }).passthrough(),
    overall: z.enum(["ok", "tight", "exceeded"]),
  })
  .passthrough();

export const CapacitySchema = z
  .object({
    label: z.string(),
    origin: z.string(),
    basis: z.string(),
    limits_note: z.string(),
    plan: z.object({ add_racks: z.number().int(), kw_per_rack: num, added_kw: num }).passthrough(),
    baseline: side,
    with_plan: side,
    verdict: z.enum(["fits", "fits_with_little_margin", "does_not_fit"]),
    racks_that_fit: z
      .object({ by_power: z.number().int().nullable(), by_cooling: z.number().int().nullable(), limit: z.number().int().nullable(), note: z.string() })
      .passthrough(),
  })
  .passthrough();
export type Capacity = z.output<typeof CapacitySchema>;
export type CapacitySide = Capacity["baseline"];
