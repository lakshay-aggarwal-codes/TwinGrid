import { useAuth } from "@/hooks/useAuth.ts";

/**
 * Persistent "you are in the read-only demo" labels. Text, not colour alone, and always visible while the demo runs.
 * `demo` comes from the access token's claim: a presentation hint only (the server enforces read-only).
 */
export function DemoBanner() {
  const { demo } = useAuth();
  if (!demo) return null;
  return (
    <div
      role="region"
      aria-label="Demo mode"
      data-testid="demo-banner"
      className="sticky top-0 z-50 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-b border-border bg-card px-3 py-1 text-xs text-foreground"
    >
      <span className="font-semibold">Read-only demo</span>
      <span>Simulated data</span>
    </div>
  );
}
