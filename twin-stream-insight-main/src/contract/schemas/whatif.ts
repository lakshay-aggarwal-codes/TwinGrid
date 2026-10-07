/** GET /api/whatif: an isolated 24 h run at constant inputs. A preview, never live state. */
import { z } from 'zod';
import { lenientEnum, num } from './common';
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
        utilisation: num,
        outside_temp_C: num,
        water_stress: num,
        mode: lenientEnum(['auto', 'free_air', 'closed_loop', 'evaporative', 'hybrid'] as const),
        chilled_water_temp_C: num,
      })
      .passthrough()
      .optional(),
    /** BC-02 [MR]: not in payloads today. */
    physics_version: z.string().optional(),
  })
  .passthrough();
export type WhatIfResponse = z.output<typeof WhatIfResponse>;
