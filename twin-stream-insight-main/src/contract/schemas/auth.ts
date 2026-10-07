/** BC-04: POST /auth/login and /auth/refresh. Roles are UX hints only; backend 403 is final. */
import { z } from 'zod';
import { lenientEnum } from './common';

export const TokenResponse = z
  .object({
    access_token: z.string().min(1),
    refresh_token: z.string().min(1),
    token_type: z.string(),
    role: lenientEnum(['viewer', 'operator'] as const),
  })
  .passthrough();
export type TokenResponse = z.output<typeof TokenResponse>;
