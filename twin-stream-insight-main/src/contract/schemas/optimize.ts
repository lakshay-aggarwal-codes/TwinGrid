/** POST /api/optimize (operator). Simulator-only output; the browser never recomputes any of it. */
import { z } from 'zod';
import { num } from './common';
import { StateResponse } from './state';

export const OptimizeSummary = z
  .object({
    mean_pue: num,
    mean_wue: num,
    mean_cooling_power_kw: num,
    total_water_consumed_L: num,
    total_reward: num,
    safety_violations: num,
  })
  .passthrough();
export type OptimizeSummary = z.output<typeof OptimizeSummary>;

export const OptimizeResult = z
  .object({
    results: z.array(StateResponse),
    summary: OptimizeSummary,
  })
  .passthrough();
export type OptimizeResult = z.output<typeof OptimizeResult>;
