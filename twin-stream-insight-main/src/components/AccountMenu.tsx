import { useAuth, useRole } from "@/hooks/useAuth.tsx";

const ROLE_LABEL: Record<string, string> = { viewer: "Viewer", operator: "Operator" };

/** Who is signed in, their role, and the sign-out control. Small and fixed so it needs no header changes. */
export function AccountMenu() {
  const { username, logout } = useAuth();
  const { role, known } = useRole();
  const roleText = role === null ? "not reported" : known ? ROLE_LABEL[role] : "unrecognised";
  return (
    <div
      role="group"
      aria-label="Account"
      className="fixed bottom-2 right-2 z-50 flex items-center gap-2 rounded-md border border-border bg-card/85 backdrop-blur-sm px-2.5 py-1 text-xs text-muted-foreground"
    >
      <span>{username}</span>
      <span
        data-testid="account-role"
        data-role-known={known}
        title="Your role only changes what this screen offers. The server decides what you may do."
      >
        Role: {roleText}
      </span>
      <button type="button" onClick={() => void logout()} className="underline underline-offset-2 hover:text-foreground">
        Sign out
      </button>
    </div>
  );
}
