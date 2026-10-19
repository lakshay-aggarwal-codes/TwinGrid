import { CircleHelp, ShieldAlert, ShieldCheck, type LucideIcon } from 'lucide-react';
import type { ConstraintState, HardConstraintView, PolicyConstraintState } from '@/evaluation/model';

/** One icon SHAPE per state; the words carry the meaning, so colour is never the only cue. */
const CELL_ICON: Record<ConstraintState, LucideIcon> = { violated: ShieldAlert, none: ShieldCheck, not_measured: CircleHelp };
const ROW_ICON: Record<PolicyConstraintState, LucideIcon> = { violated: ShieldAlert, clean: ShieldCheck, partial: CircleHelp };

/**
 * Hard constraints, shown BEFORE the metrics table and separate from reward: a better score never offsets a
 * violated limit. A limit the report did not count reads "not measured" (never zero). Neutral styling for every
 * state: a violation is louder because of its words, icon shape and heavier border, not because a clean row is
 * painted as a success.
 */
export function HardConstraintPanel({ view }: { view: HardConstraintView }) {
  return (
    <section aria-label="Hard constraints" data-testid="hard-constraints" data-violating-policies={view.violatingPolicies} className="space-y-1.5 rounded-md border-2 border-border p-3">
      <h2 className="text-sm font-semibold text-foreground">Hard constraints (safety envelope)</h2>
      <p className="text-xs text-foreground" data-testid="hard-constraints-headline">
        {view.headline}
      </p>
      <p className="text-[11px] text-muted-foreground">
        Mean violating steps per test episode. 0 means no episode violated the limit; above 0 means at least one did. These are separate from the reward and are never
        traded against it. Simulated results only.
      </p>
      {view.backendNote !== null && (
        <p className="text-xs text-foreground" data-testid="hard-constraints-note">
          {view.backendNote}
        </p>
      )}
      {view.comparatorCaveat !== null && (
        <p className="text-xs text-foreground" data-testid="comparator-caveat">
          {view.comparatorCaveat}
        </p>
      )}
      {view.rows.length > 0 && (
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Hard-constraint table (scrollable)">
          <table className="w-full text-left text-xs" data-testid="hard-constraints-table">
            <caption className="sr-only">Hard-constraint violations per policy and limit, mean violating steps per test episode</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="p-2 font-medium text-foreground">
                  Policy
                </th>
                <th scope="col" className="p-2 font-medium text-foreground">
                  Status
                </th>
                {view.limits.map((l) => (
                  <th key={l.id} scope="col" className="p-2 font-medium text-foreground" data-limit={l.id}>
                    {l.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.rows.map((r) => {
                const RowIcon = ROW_ICON[r.state];
                return (
                  <tr key={r.policyId} data-hc-row={r.policyId} data-hc-state={r.state} className="border-b border-border last:border-0">
                    <th scope="row" className="p-2 font-mono font-medium text-foreground">
                      {r.policyId}
                    </th>
                    <td className="p-2 text-foreground" data-hc-status>
                      <span className="flex items-start gap-1.5">
                        <RowIcon aria-hidden="true" data-hc-icon={r.state} className="mt-px h-3.5 w-3.5 shrink-0" />
                        <span className={r.state === 'violated' ? 'font-semibold' : undefined}>{r.summary}</span>
                      </span>
                    </td>
                    {r.cells.map((c) => {
                      const Icon = CELL_ICON[c.state];
                      return (
                        <td key={c.id} className="p-2 font-mono text-foreground" data-hc-cell={c.id} data-hc-cell-state={c.state} title={c.value === null ? undefined : String(c.value)}>
                          <span className="flex items-start gap-1">
                            <Icon aria-hidden="true" data-hc-icon={c.state} className="mt-px h-3 w-3 shrink-0" />
                            <span className={c.state === 'violated' ? 'font-semibold' : undefined}>{c.text}</span>
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
