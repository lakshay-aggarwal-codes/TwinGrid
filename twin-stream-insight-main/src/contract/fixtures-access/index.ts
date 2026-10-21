/**
 * AUTH-C fixtures: the frozen §8.1 (access requests) and §8.3 (demo session) example bodies, verbatim.
 * The Visitor UX is built and tested against these so it does not depend on the backend being present.
 * Contains no credentials: the "tokens" below are inert placeholders.
 */

/** 202 from POST /api/access-requests */
export const accessRequestCreated = {
  ref: 'AR-7K3Q9X',
  status: 'pending',
  status_token: 'status-token-placeholder',
  expires_at: '2026-11-20T12:00:00Z',
  message: 'Request received.',
} as const;

/** 200 from GET /api/access-requests/{ref}/status, one per documented status. */
const statusBase = { ref: 'AR-7K3Q9X', expires_at: '2026-11-20T12:00:00Z', updated_at: '2026-10-21T09:30:00Z' } as const;
export const statusPending = { ...statusBase, status: 'pending', can_activate: false } as const;
export const statusApproved = { ...statusBase, status: 'approved', can_activate: true } as const;
export const statusActivated = { ...statusBase, status: 'activated', can_activate: false } as const;
export const statusRejected = { ...statusBase, status: 'rejected', can_activate: false } as const;
export const statusExpired = { ...statusBase, status: 'expired', can_activate: false } as const;

/** 202 from POST /api/access-requests/resend-activation */
export const resendAck = { message: 'If your request is approved, a new link has been sent.' } as const;

/** 200 from POST /api/access-requests/activate */
export const activateOk = { status: 'activated' } as const;
/** 400 from POST /api/access-requests/activate */
export const activateInvalid = { error: 'invalid_or_expired' } as const;

/** 422 from POST /api/access-requests */
export const invalidRequest = { error: 'invalid_request' } as const;
/** 404 for an unknown ref OR a wrong token (identical by design). */
export const notFound = { error: 'not_found' } as const;

/** 200 from POST /auth/demo-session (no refresh token is issued). */
export const demoSession = {
  access_token: 'demo-access-token-placeholder',
  token_type: 'bearer',
  expires_in: 1800,
  role: 'viewer',
  demo: true,
} as const;
/** 503 from POST /auth/demo-session */
export const demoUnavailable = { error: 'demo_unavailable' } as const;
