import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { StateBoundary } from "@/state/StateBoundary";
import { useApiQuery } from "@/state/useApiQuery";
import { decideProposal, fetchProposals, proposalsKey } from "./api";
import { EffectTable } from "./EffectTable";
import { APPROVAL_NOTE, MAX_NOTE_CHARS, decisionBlock, modeLabel, type Proposal } from "./model";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

// eslint-disable-next-line react-refresh/only-export-components -- non-component export used elsewhere; only costs a full reload in dev
export function decideErrorText(e: unknown): string {
  if (e instanceof AuthRequiredError) return "Your session has ended. Sign in again.";
  if (e instanceof ApiError) {
    if (e.code === "self_decision") return "You made this proposal, so someone else must decide it.";
    if (e.kind === "forbidden") return "Only an admin can approve or reject.";
    if (e.kind === "conflict") return "This proposal was already decided. Reload to see the result.";
    if (e.kind === "not_found") return "This proposal no longer exists.";
  }
  return "The decision could not be recorded. Try again.";
}

const WORD = { pending: "Pending", approved: "Approved", rejected: "Rejected" } as const;

function Row({ p, role, username }: { p: Proposal; role: string | null; username: string | null }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const block = decisionBlock(role, username, p);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const row = await decideProposal(p.id, decision, note);
      client.setQueryData<Proposal[]>(proposalsKey, (old) => (old ? old.map((x) => (x.id === row.id ? row : x)) : old));
    } catch (e) {
      setError(decideErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li data-testid="proposal" data-status={p.status} className="space-y-2 p-3">
      <p className="text-sm">
        <strong>#{p.id}</strong> · <span data-testid="proposal-status">{WORD[p.status]}</span> ·{" "}
        {p.chilled_water_temp_C.toFixed(1)} °C, {modeLabel(p.cooling_mode)} · source: {p.source} · by {p.proposer}
      </p>
      {p.rationale ? <p className="text-xs">Reason: {p.rationale}</p> : null}
      {p.decided_by ? (
        <p className="text-xs text-muted-foreground">
          {WORD[p.status]} by {p.decided_by}
          {p.decision_note ? `: ${p.decision_note}` : ""}
        </p>
      ) : null}
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground">Predicted effect when it was proposed</summary>
        <EffectTable effect={p.predicted} caption={`Proposal #${p.id}`} />
      </details>
      {p.status === "pending" && role === "admin" ? (
        <div className="space-y-1.5">
          {block ? (
            <p className="text-xs text-muted-foreground">{block}</p>
          ) : (
            <>
              <label htmlFor={`decision-note-${p.id}`} className="block text-xs text-muted-foreground">
                Note (optional, up to {MAX_NOTE_CHARS} characters)
              </label>
              <input
                id={`decision-note-${p.id}`}
                value={note}
                maxLength={MAX_NOTE_CHARS}
                onChange={(e) => setNote(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <div className="flex gap-2">
                <button type="button" className={BTN} disabled={busy} onClick={() => void decide("approve")}>
                  Approve
                </button>
                <button type="button" className={BTN} disabled={busy} onClick={() => void decide("reject")}>
                  Reject
                </button>
              </div>
            </>
          )}
          {error ? (
            <p role="alert" className="text-xs text-destructive-text">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function ProposalsPanel({ role, username }: { role: string | null; username: string | null }) {
  const { state, refetch } = useApiQuery<Proposal[]>({
    queryKey: proposalsKey,
    queryFn: ({ signal }) => fetchProposals(signal),
    staleTime: 10_000,
    isEmpty: (rows) => rows.length === 0,
  });
  return (
    <section aria-labelledby="prop-h" className="space-y-2 rounded-md border border-border bg-card p-3">
      <h2 id="prop-h" className="text-sm font-semibold">
        Proposals and approvals
      </h2>
      <p className="text-xs text-muted-foreground">
        An operator proposes; a different admin approves or rejects. Every step is audit-logged. {APPROVAL_NOTE}
      </p>
      <StateBoundary state={state} onRetry={refetch} block={false} messages={{ empty: "No proposals yet." }}>
        {(rows) => (
          <ul aria-label="Proposals" className="divide-y divide-border rounded-md border border-border">
            {rows.map((p) => (
              <Row key={p.id} p={p} role={role} username={username} />
            ))}
          </ul>
        )}
      </StateBoundary>
    </section>
  );
}
