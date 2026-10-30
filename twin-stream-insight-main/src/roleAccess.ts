/**
 * The one client-side definition of "may operate" (UX gating ONLY; the backend enforces roles on every request).
 *
 * Mirrors the server's `User.can_operate()`: role `operator` or `admin`. A viewer is read-only. It lives in its own
 * dependency-free module and is re-exported from `hooks/useAuth.ts` (the documented home), so components can use it
 * without importing the hook module.
 */

/** Exact text for a control only an operating role (operator or admin) may use. */
export const OPERATOR_REQUIRED_TEXT = "Requires operator role";

/** True only for the exact backend values "operator" and "admin". Anything else (viewer, unknown, null) may not operate. */
export function canOperate(role: string | null | undefined): boolean {
  return role === "operator" || role === "admin";
}

/**
 * True when a signed-in user may NOT operate (a viewer, or a role this client does not recognise): the controls that
 * compute, simulate, save or edit are shown locked. A signed-out state (null) is not "read-only": the app is not shown
 * at all then (AuthGate), so there is nothing to lock.
 */
export function isReadOnly(role: string | null | undefined): boolean {
  return role !== null && role !== undefined && !canOperate(role);
}
