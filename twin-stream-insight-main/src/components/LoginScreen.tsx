import { useRef, useState, type FormEvent } from "react";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DemoError, LoginError } from "@/authClient";
import { useAuth } from "@/hooks/useAuth.ts";
import { usePageTitle } from "@/hooks/usePageTitle";
import { RequestAccessForm } from "@/features/access/RequestAccessForm";
import { navigateTo, saveTicket } from "@/features/access/ticket";

/**
 * Sign-in screen. There is deliberately no "create account" control: accounts are provisioned by an administrator
 * (see ALLOW_PUBLIC_REGISTRATION on the backend). A visitor without one can ASK for read-only access (reviewed by the
 * owner, then activated from an emailed link) or explore the read-only demo, which needs no account at all.
 */
export function LoginScreen() {
  const [view, setView] = useState<"signin" | "request">("signin");
  usePageTitle(view === "request" ? "Request viewer access – TwinGrid" : "Sign in – TwinGrid");
  const { login, notice, startDemo } = useAuth();
  const [demoError, setDemoError] = useState<string | null>(null);
  const [demoStarting, setDemoStarting] = useState(false);
  const demoStartingRef = useRef(false);
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

  async function onDemo() {
    if (demoStartingRef.current) return;
    demoStartingRef.current = true;
    setDemoStarting(true);
    setDemoError(null);
    try {
      await startDemo();
      // On success the auth gate swaps this screen out.
    } catch (e) {
      setDemoError(e instanceof DemoError ? e.message : "The demo could not be started. Please try again.");
      demoStartingRef.current = false;
      setDemoStarting(false);
    }
  }

  if (view === "request") {
    return (
      <main className="min-h-screen flex items-start justify-center bg-background p-4 sm:items-center">
        <RequestAccessForm
          onBack={() => setView("signin")}
          onSubmitted={(created) => {
            saveTicket({ ref: created.ref, token: created.status_token });
            navigateTo("/access/pending");
          }}
        />
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-start justify-center bg-background p-4 sm:items-center">
      <div className="w-full min-w-0 max-w-sm space-y-4">
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
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "login-error" : undefined}
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
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "login-error" : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {/* Why you are here when you did not sign out yourself (e.g. "Session ended — sign in again"). Text + icon. */}
        {notice && (
          <div
            role="alert"
            data-testid="session-notice"
            className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-2 text-sm text-foreground"
          >
            <LogOut className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{notice}</span>
          </div>
        )}

        {/* A failed sign-in attempt, tied to both fields. */}
        {error && (
          <p id="login-error" role="alert" className="text-sm text-destructive-text">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={submitting || !username.trim() || !password}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <section aria-labelledby="visitor-heading" className="space-y-3 rounded-lg border border-border bg-card p-4 sm:p-6">
        <div className="space-y-1">
          <h2 id="visitor-heading" className="text-base font-semibold">
            Just visiting?
          </h2>
          <p className="text-sm text-muted-foreground">
            Ask the owner for read-only access, or look around a read-only demo that uses simulated data.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <Button type="button" variant="outline" className="w-full" onClick={() => setView("request")}>
            Request viewer access
          </Button>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => void onDemo()}
            disabled={demoStarting}
            aria-describedby={demoError ? "demo-error" : undefined}
          >
            {demoStarting ? "Starting demo…" : "Explore read-only demo"}
          </Button>
        </div>
        {demoError && (
          <p id="demo-error" role="alert" className="text-sm text-destructive-text">
            {demoError}
          </p>
        )}
      </section>
      </div>
    </main>
  );
}
