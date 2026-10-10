import type { TableView } from '@/evaluation/model';

/**
 * Policies as rows in the backend's order; metrics as columns, only those the backend reported. No sorting, no
 * highlighting, no "best" marker: the table has no concept of a winner. Cell values are shown as sent (rounded for
 * display only; the exact value is in the tooltip). Per-policy means come with no uncertainty and say so.
 */
export function EvaluationTable({ view }: { view: TableView }) {
  return (
    <div className="space-y-1">
      <div className="overflow-x-auto rounded-md border border-border" tabIndex={0} role="region" aria-label="Policy comparison table (scrollable)">
        <table className="w-full text-left text-xs" data-testid="evaluation-table">
          <caption className="sr-only">Metrics per policy, in the order the backend returned them</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="p-2 font-medium text-foreground">
                Policy
              </th>
              {view.columns.map((c) => (
                <th key={c.id} scope="col" className="p-2 align-top font-medium text-foreground" data-metric={c.id} title={c.definition ?? undefined}>
                  <span className="font-mono">{c.id}</span>
                  {c.hint !== null && <span className="block text-[10px] font-normal text-muted-foreground">{c.hint}</span>}
                  {c.caveat !== null && <span className="block text-[10px] font-normal text-muted-foreground">{c.caveat}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.rows.map((r) => (
              <tr key={r.policyId} data-policy-row={r.policyId} className="border-b border-border last:border-0">
                <th scope="row" className="p-2 font-mono font-medium text-foreground">
                  {r.policyId}
                  {r.kind !== null && r.kind !== r.policyId && <span className="block text-[10px] font-normal text-muted-foreground">{r.kind}</span>}
                </th>
                {r.cells.map((cell, i) => (
                  <td key={view.columns[i].id} className="p-2 font-mono text-foreground" title={cell.exact ?? undefined} data-cell={view.columns[i].id}>
                    {cell.text}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted-foreground" data-testid="table-uncertainty">
        Per-policy values as reported by the backend; uncertainty not provided.
      </p>
    </div>
  );
}
