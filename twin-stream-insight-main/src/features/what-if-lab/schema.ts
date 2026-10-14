/** Task 15: contract for `GET /api/whatif/sensitivity` (api/plugins/whatif.py). Shape only; values are never defaulted. */
import { z } from "zod";

const num = z.number().finite();
const metrics = z.record(num);

export const SweepSchema = z
  .object({
    label: z.string(),
    basis: z.string(),
    runs: z.number().int().nonnegative(),
    max_runs: z.number().int().positive(),
    inputs: z.object({ utilisation: num, outside_temp_C: num, water_stress: num, mode: z.string(), chilled_water_temp_C: num }).passthrough(),
    outlet_limit_C: num,
    carbon_data_is_real: z.boolean(),
    baseline: metrics,
    parameters: z.array(
      z.object({
        parameter: z.string(),
        label: z.string(),
        unit: z.string().nullable(),
        base: z.union([num, z.string()]),
        variants: z.array(z.object({ direction: z.string(), value: z.union([num, z.string()]), metrics, deltas: metrics }).passthrough()),
      }),
    ),
  })
  .passthrough();
export type Sweep = z.output<typeof SweepSchema>;
