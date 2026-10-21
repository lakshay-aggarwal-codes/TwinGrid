import { AlertTriangle, Clock, Info } from "lucide-react";
import { Link } from "react-router-dom";
import { EvidenceTable } from "./EvidenceTable";
import { hasWeakEvidence, isSafeLink, modeLabel, segmentsOf, warningText } from "./model";
import type { CopilotResponse } from "./schema";

function focusEvidence(turnId: number, id: string) {
  const row = document.getElementById(`evidence-${turnId}-${id}`);
  row?.scrollIntoView?.({ block: "nearest" });
  row?.focus();
}

/** One answer. Everything from the server is rendered as TEXT: no HTML, no markdown, links only from `links[]` and only to known routes. */
export function AnswerView({ turnId, data, knownRoutes, onNavigate }: { turnId: number; data: CopilotResponse; knownRoutes: readonly string[]; onNavigate: () => void }) {
  const weak = hasWeakEvidence(data.evidence);
  return (
    <div className="space-y-3" data-testid="answer" data-mode={data.mode}>
      <p data-testid="answer-mode" className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] font-medium">
        <Info aria-hidden="true" className="h-3 w-3" />
        {modeLabel(data.mode)}
        {data.limits.provider_configured ? "" : " · no language model is configured"}
      </p>

      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed" data-testid="answer-text">
        {segmentsOf(data.answer, data.evidence).map((s, i) =>
          s.type === "text" ? (
            <span key={i}>{s.text}</span>
          ) : (
            <button
              key={i}
              type="button"
              data-testid={`cite-${s.id}`}
              aria-label={`Evidence ${s.id}`}
              onClick={() => focusEvidence(turnId, s.id)}
              className="mx-0.5 rounded border border-border bg-muted px-1 font-mono text-[11px] font-semibold hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {s.id}
            </button>
          ),
        )}
      </p>

      {weak ? (
        <p role="note" data-testid="answer-stale" className="flex items-start gap-1.5 rounded border border-dashed border-border bg-muted/50 p-2 text-xs">
          <Clock aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Some evidence is stale or unavailable. Read the values below as out of date, not as normal.
        </p>
      ) : null}

      {data.warnings.length > 0 ? (
        <ul role="note" aria-label="Warnings" data-testid="answer-warnings" className="space-y-1 rounded border border-dashed border-border p-2 text-xs">
          {data.warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <AlertTriangle aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {warningText(w)}
            </li>
          ))}
        </ul>
      ) : null}

      {data.unknowns.length > 0 ? (
        <section aria-label="Not known" data-testid="answer-unknowns" className="rounded border border-dotted border-border p-2">
          <h3 className="text-xs font-semibold">Not known from the available evidence</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
            {data.unknowns.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <EvidenceTable turnId={turnId} evidence={data.evidence} />

      {data.links.length > 0 ? (
        <ul aria-label="Related pages" className="flex flex-wrap gap-2 text-xs" data-testid="answer-links">
          {data.links.map((l, i) => (
            <li key={i}>
              {isSafeLink(l.path, knownRoutes) ? (
                <Link to={l.path} onClick={onNavigate} className="text-primary underline">
                  {l.label}
                </Link>
              ) : (
                <span data-testid="link-unavailable" className="text-muted-foreground">
                  {l.label} (no page for this in the app)
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-[10px] text-muted-foreground">Request {data.request_id}</p>
    </div>
  );
}
