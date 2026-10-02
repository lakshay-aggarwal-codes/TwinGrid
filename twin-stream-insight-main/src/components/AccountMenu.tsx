import { useAuth } from "@/hooks/useAuth.ts";

/** Who is signed in, their role, and the sign-out control. Small and fixed so it needs no header changes. */
export function AccountMenu() {
  const { username, role, logout } = useAuth();
  return (
    <div
      role="group"
      aria-label="Account"
      className="fixed bottom-2 right-2 z-50 flex items-center gap-2 rounded-md border border-border bg-card/85 backdrop-blur-sm px-2.5 py-1 text-xs text-muted-foreground"
    >
      <span>
        {username} <span className="uppercase tracking-wide">({role})</span>
      </span>
      <button type="button" onClick={() => void logout()} className="underline underline-offset-2 hover:text-foreground">
        Sign out
      </button>
    </div>
  );
}
