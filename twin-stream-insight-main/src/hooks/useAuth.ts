import { useCallback, useSyncExternalStore } from "react";
import {
  getAuthSnapshot,
  login as authLogin,
  logout as authLogout,
  subscribeAuth,
  type AuthRole,
  type AuthSnapshot,
} from "@/authClient";

export interface UseAuth extends AuthSnapshot {
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

/** Reactive view of the sign-in state held by authClient.ts. */
export function useAuth(): UseAuth {
  const snapshot = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot);
  const login = useCallback((username: string, password: string) => authLogin(username, password), []);
  const logout = useCallback(() => authLogout(), []);
  return { ...snapshot, login, logout };
}

/** Exact text for a control only an operator may use (optimise, acknowledge). */
export const OPERATOR_REQUIRED_TEXT = "Requires operator role";

export interface RoleView {
  /** The role exactly as the backend stated it; null when signed out. */
  role: AuthRole | null;
  /** The role is one this client recognises (viewer / operator). An unrecognised role stays visible as unrecognised. */
  known: boolean;
  isOperator: boolean;
  /**
   * For an operator-only control: spread `disabled` onto it and show `reason` as text beside it (never colour alone).
   * `reason` is null when the control is enabled.
   */
  operatorOnly: { disabled: boolean; reason: string | null };
}

/** Pure; exported for tests. Only the exact backend value "operator" enables operator controls in the UI. */
export function roleView(role: AuthRole | null): RoleView {
  const isOperator = role === "operator";
  return {
    role,
    known: role === "viewer" || role === "operator",
    isOperator,
    operatorOnly: { disabled: !isOperator, reason: isOperator ? null : OPERATOR_REQUIRED_TEXT },
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
