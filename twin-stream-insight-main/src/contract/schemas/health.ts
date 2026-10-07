/**
 * BC-15. /api/health (JWT) always says "healthy" when reachable: it proves the API answered, nothing more.
 * /healthz is unauthenticated; a failure is HTTP 503 with a generic body, which is not parsed here.
 * NOTE (contract finding): both `timestamp` values are naive local `datetime.now().isoformat()` on the backend.
 */
import { z } from 'zod';
import { lenientEnum } from './common';

export const ApiHealth = z
  .object({
    status: lenientEnum(['healthy'] as const),
    timestamp: z.string(),
  })
  .passthrough();
export type ApiHealth = z.output<typeof ApiHealth>;

export const Healthz = z
  .object({
    status: lenientEnum(['ok'] as const),
    database: lenientEnum(['ok'] as const),
    timestamp: z.string(),
  })
  .passthrough();
export type Healthz = z.output<typeof Healthz>;
