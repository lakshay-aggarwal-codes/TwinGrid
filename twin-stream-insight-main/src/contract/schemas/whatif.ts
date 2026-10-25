/** GET /api/whatif: an isolated 24 h run at constant inputs. A preview, never live state. */
import { z } from 'zod';
import { lenientEnum, num, utilisationFraction } from './common';
import { CoolingMode } from './state';

export const WhatIfResponse = z
  .object({
    hours: num,
    basis: z.string(),
    mean_pue: num,
    wue: num,
    total_water_L: num,
    total_energy_kwh: num,
    total_co2_kg: num,
    max_outlet_temp_C: num,
    final_cooling_mode: CoolingMode,
    drought_override_active: z.boolean(),
    carbon_data_is_real: z.boolean(),
    // Echo of the request. Optional: older backends do not send it.
    inputs: z
      .object({
        utilisation: utilisationFraction,
        outside_temp_C: num,
        water_stress: num,
        mode: lenientEnum(['auto', 'free_air', 'closed_loop', 'evaporative', 'hybrid'] as const),
        chilled_water_temp_C: num,
      })
      .passthrough()
      .optional(),
    /** The physics version the answer came from (R3 Task 2; absent on older backends). */
    physics_version: z.string().optional(),
    /** R3 Task 2: what the answer is made of. Same vocabulary as a run result's `provenance`; absent on older backends. */
    provenance: z
      .object({
        origin: z.string(),
        scenario_kind: z.string().nullable(),
        weather_source: z.string(),
        plant: z.string(),
        control: z.string(),
        model_version: z.string().nullable(),
        registry_version: z.string(),
        api_version: z.string(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();
export type WhatIfResponse = z.output<typeof WhatIfResponse>;
