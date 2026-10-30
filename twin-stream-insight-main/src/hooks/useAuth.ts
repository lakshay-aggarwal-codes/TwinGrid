import { useCallback, useSyncExternalStore } from "react";
import { OPERATOR_REQUIRED_TEXT, canOperate } from "@/roleAccess";
import {
  getAuthSnapshot,
  login as authLogin,
  startDemoSession,
  logout as authLogout,
  subscribeAuth,
  type AuthRole,
  type AuthSnapshot,
} from "@/authClient";

export interface UseAuth extends AuthSnapshot {
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Start the read-only demo session (no credentials). Rejects with DemoError. */
  startDemo: () => Promise<void>;
}

/** Reactive view of the sign-in state held by authClient.ts. */
export function useAuth(): UseAuth {
  const snapshot = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot);
  const login = useCallback((username: string, password: string) => authLogin(username, password), []);
  const logout = useCallback(() => authLogout(), []);
  const startDemo = useCallback(() => startDemoSession(), []);
  return { ...snapshot, login, logout, startDemo };
}

/** Exact text for a control only an operating role (operator or admin) may use (optimise, acknowledge, run). */
export { OPERATOR_REQUIRED_TEXT, canOperate };

export interface RoleView {
  /** The role exactly as the backend stated it; null when signed out. */
  role: AuthRole | null;
  /** The role is one this client recognises (viewer / operator / admin). An unrecognised role stays visible as unrecognised. */
  known: boolean;
  /** May operate: role operator or admin (see canOperate). Same value as `canOperate`; kept under its original name. */
  isOperator: boolean;
  /** May operate: role operator or admin. Admin sees exactly the controls an operator sees. */
  canOperate: boolean;
  /**
   * For an operator-only control: spread `disabled` onto it and show `reason` as text beside it (never colour alone).
   * `reason` is null when the control is enabled.
   */
  operatorOnly: { disabled: boolean; reason: string | null };
}

/** Pure; exported for tests. Only the exact backend values "operator" and "admin" enable operator controls in the UI. */
export function roleView(role: AuthRole | null): RoleView {
  const operate = canOperate(role);
  return {
    role,
    known: role === "viewer" || role === "operator" || role === "admin",
    isOperator: operate,
    canOperate: operate,
    operatorOnly: { disabled: !operate, reason: operate ? null : OPERATOR_REQUIRED_TEXT },
  };
}

/**
 * The signed-in role, for UX gating ONLY.
 *
 * NOT AUTHORITATIVE: this decides what the interface offers, never what is allowed. The backend enforces roles on
 * every request; a 403 is final and must still be handled and shown even when this says the control is enabled
 * (the role can change server-side after sign-in). Never use it to hide data the server would send anyway.
 */
export function useRole(): RoleView {
  const { role } = useAuth();
  return roleView(role);
}
