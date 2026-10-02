import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoginError } from "@/authClient";
import { useAuth } from "@/hooks/useAuth.ts";
import { usePageTitle } from "@/hooks/usePageTitle";

/**
 * Sign-in screen. There is deliberately no "create account" control: accounts are
 * provisioned by an administrator (see ALLOW_PUBLIC_REGISTRATION on the backend).
 */
export function LoginScreen() {
  usePageTitle("Sign in – TwinGrid");
  const { login, notice } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      // On success the auth gate swaps this screen out; nothing more to do here.
    } catch (e) {
      setError(e instanceof LoginError ? e.message : "Sign-in failed. Please try again.");
      setPassword("");
      setSubmitting(false);
    }
  }

  const message = error ?? notice;

  return (
    <main className="min-h-screen flex items-center justify-center bg-background p-4">
      <form
        onSubmit={onSubmit}
        aria-labelledby="login-heading"
        className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6"
      >
        <div className="space-y-1">
          <h1 id="login-heading" className="text-xl font-semibold">
            Sign in to TwinGrid
          </h1>
          <p className="text-sm text-muted-foreground">Use the account an administrator created for you.</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="login-username">Username</Label>
          <Input
            id="login-username"
            name="username"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {message && (
          <p role="alert" className="text-sm text-destructive">
            {message}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={submitting || !username.trim() || !password}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
