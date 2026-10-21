/** Runtime schemas for the frozen §8.1 / §8.3 bodies. A body that does not match is "unexpected", never repaired. */
import { z } from 'zod';

export const ACCESS_STATUSES = ['pending', 'approved', 'activated', 'rejected', 'expired'] as const;
export type AccessStatus = (typeof ACCESS_STATUSES)[number];

export const AccessRequestCreated = z
  .object({
    ref: z.string().min(1),
    status: z.literal('pending'),
    status_token: z.string().min(1),
    expires_at: z.string(),
    message: z.string(),
  })
  .passthrough();
export type AccessRequestCreated = z.output<typeof AccessRequestCreated>;

export const AccessRequestStatus = z
  .object({
    ref: z.string().min(1),
    status: z.enum(ACCESS_STATUSES),
    expires_at: z.string(),
    updated_at: z.string(),
    can_activate: z.boolean(),
  })
  .passthrough();
export type AccessRequestStatus = z.output<typeof AccessRequestStatus>;

export const ResendAck = z.object({ message: z.string() }).passthrough();
export const ActivateOk = z.object({ status: z.literal('activated') }).passthrough();

/** POST /auth/demo-session: note there is NO refresh_token. */
export const DemoSessionResponse = z
  .object({
    access_token: z.string().min(1),
    token_type: z.string(),
    expires_in: z.number(),
    role: z.string(),
    demo: z.boolean(),
  })
  .passthrough();
export type DemoSessionResponse = z.output<typeof DemoSessionResponse>;
