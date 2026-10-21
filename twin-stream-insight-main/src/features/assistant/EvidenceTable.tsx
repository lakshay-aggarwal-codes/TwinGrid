import { AlertTriangle, CheckCircle2, Clock, FileText, HelpCircle, type LucideIcon } from "lucide-react";
import { FRESHNESS_VIEW, ORIGIN_VIEW, observedText, valueText } from "./model";
import type { Evidence, Freshness } from "./schema";

const FRESH_ICON: Record<Freshness, LucideIcon> = { fresh: CheckCircle2, stale: Clock, unavailable: AlertTriangle, static: FileText };
// Freshness is carried by the icon shape and the words, never by colour alone; stale/unavailable also get a dashed border.
const FRESH_BORDER: Record<Freshness, string> = { fresh: "border-solid", stale: "border-dashed", unavailable: "border-dashed", static: "border-dotted" };

/** Every number the answer relies on, inspectable: source, entity, field, value and unit, when, where from, how fresh. Text only. */
export function EvidenceTable({ turnId, evidence }: { turnId: number; evidence: readonly Evidence[] }) {
  if (evidence.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="evidence-none">
        No evidence was found for this question, so the answer states no values.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]" data-testid="evidence-table">
        <caption className="pb-1 text-left text-xs font-semibold">Evidence</caption>
        <thead className="text-muted-foreground">
          <tr>
            {["Ref", "Source", "Entity", "Field", "Value", "Observed at", "Origin", "Freshness"].map((h) => (
              <th key={h} scope="col" className="px-1 py-0.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {evidence.map((e) => {
            const Icon = FRESH_ICON[e.freshness];
            return (
              <tr key={e.id} id={`evidence-${turnId}-${e.id}`} tabIndex={-1} data-testid={`evidence-row-${e.id}`} className="border-t border-border align-top focus:bg-muted focus:outline-none">
                <th scope="row" className="px-1 py-0.5 font-mono font-semibold">
                  {e.id}
                </th>
                <td className="px-1 py-0.5 break-words">{e.source}</td>
                <td className="px-1 py-0.5 break-words">{e.entity}</td>
                <td className="px-1 py-0.5 break-words">{e.field}</td>
                <td className="px-1 py-0.5 break-words" data-testid={`evidence-value-${e.id}`}>
                  {valueText(e)}
                </td>
                <td className="px-1 py-0.5 whitespace-nowrap">{observedText(e.observed_at)}</td>
                <td className="px-1 py-0.5">
                  <span data-testid={`evidence-origin-${e.id}`} className="inline-flex items-center gap-1 rounded border border-dashed border-border px-1">
                    <HelpCircle aria-hidden="true" className="h-3 w-3" />
                    {ORIGIN_VIEW[e.origin]}
                  </span>
                </td>
                <td className="px-1 py-0.5">
                  <span data-testid={`evidence-freshness-${e.id}`} title={FRESHNESS_VIEW[e.freshness].note} className={`inline-flex items-center gap-1 rounded border px-1 ${FRESH_BORDER[e.freshness]}`}>
                    <Icon aria-hidden="true" className="h-3 w-3" />
                    {FRESHNESS_VIEW[e.freshness].text}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
