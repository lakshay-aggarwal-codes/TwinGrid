/** GET /api/equipment/health: methodology metrics on a PROXY dataset, not live per-rack health. */
import { z } from 'zod';
import { num } from './common';

const Metrics = z.object({ mae: num, rmse: num, r2: num }).passthrough();

export const EquipmentHealth = z
  .object({
    available: z.boolean(),
    message: z.string().optional(),
    trained_at_utc: z.string().optional(),
    subset: z.string().optional(),
    baseline: Metrics.optional(),
    lstm: Metrics.optional(),
    mae_improvement_pct: num.optional(),
    beats_baseline: z.boolean().optional(),
    dataset_caveat: z.string().optional(),
  })
  .passthrough();
export type EquipmentHealth = z.output<typeof EquipmentHealth>;
