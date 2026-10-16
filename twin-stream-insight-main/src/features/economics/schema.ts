/** Task 25: contract for `GET /api/economics/summary` (api/plugins/economics.py). Shape only; values are never defaulted. */
import { z } from "zod";

const num = z.number().finite();
const cost = z
  .object({ energy_kwh: num, peak_kwh: num, off_peak_kwh: num, energy_cost: num, peak_kw: num, demand_cost: num, total_cost: num })
  .passthrough();
const side = z.object({ inputs: z.record(z.unknown()), mean_pue: num, cost }).passthrough();

export const EconomicsSchema = z
  .object({
    label: z.string(),
    estimate_label: z.string(),
    origin: z.string(),
    basis: z.string(),
    currency: z.string(),
    currency_note: z.string(),
    is_default_tariff: z.boolean(),
    scenario: side,
    baseline: side,
    savings: z.object({ energy_cost: num, demand_cost: num, total_cost: num, total_pct: num.nullable() }).passthrough(),
    carbon_data_is_real: z.boolean(),
  })
  .passthrough();
export type Economics = z.output<typeof EconomicsSchema>;
