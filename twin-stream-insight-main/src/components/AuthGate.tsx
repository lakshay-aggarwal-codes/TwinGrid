import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { initAuth } from "@/authClient";
import { useAuth } from "@/hooks/useAuth.ts";
import { LoginScreen } from "@/components/LoginScreen";
import { AccountMenu } from "@/components/AccountMenu.tsx";

/**
 * Nothing behind the gate (and so no API request and no WebSocket) exists until
 * there is a signed-in user. On sign-out the gate unmounts everything behind it,
 * which closes the socket, and the query cache is dropped so the next user never
 * sees the previous user's data.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const queryClient = useQueryClient();

  useEffect(() => {
    void initAuth();
  }, []);

  useEffect(() => {
    if (status === "signed-out") queryClient.clear();
  }, [status, queryClient]);

  if (status === "restoring") {
    return (
      <div role="status" className="min-h-screen flex items-center justify-center text-sm text-muted-foreground">
        Signing in…
      </div>
    );
  }
  if (status === "signed-out") return <LoginScreen />;
  return (
    <>
      {children}
      <AccountMenu />
    </>
  );
}
