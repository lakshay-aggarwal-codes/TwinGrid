import { useCallback, useSyncExternalStore } from "react";
import {
  getAuthSnapshot,
  login as authLogin,
  logout as authLogout,
  subscribeAuth,
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
