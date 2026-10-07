/** One row of GET /api/alerts (BC-05). Timestamps are naive-UTC today (BC-14): see parseInstant(..., 'alert'). */
import { z } from 'zod';
import { lenientEnum, num } from './common';

export const AlertSeverity = lenientEnum(['INFO', 'WARNING', 'CRITICAL'] as const);

export const AlertRecord = z
  .object({
    id: num,
    created_at: z.string().nullable(),
    type: z.string(),
    message: z.string(),
    severity: AlertSeverity,
    score: num,
    alert: z.boolean(),
    acknowledged: z.boolean(),
    acknowledged_by: z.string().nullable(),
    acknowledged_at: z.string().nullable(),
    // Provenance (backend M2): null on alerts created before it; absent on older backends.
    origin: lenientEnum(['measured', 'simulated', 'replayed'] as const).nullable().optional(),
    model_version: z.string().nullable().optional(),
    dedupe_key: z.string().nullable().optional(),
  })
  .passthrough();
export type AlertRecord = z.output<typeof AlertRecord>;

export const AlertList = z.array(AlertRecord);
export type AlertList = z.output<typeof AlertList>;
