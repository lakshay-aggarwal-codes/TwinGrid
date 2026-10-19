import { useState } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import { writeErrorText } from "./errors";
import { ACTION_LABEL, ORDER_STATUS_LABEL, PRIORITY_LABEL, originText } from "./model";
import { ORDER_STATUSES, type WorkOrder } from "./schema";
import { useWorkOrderActions, useWorkOrders } from "./useMaintenance";

const BTN =
  "rounded-md border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function OrderRow({ o, canWrite }: { o: WorkOrder; canWrite: boolean }) {
  const { setStatus } = useWorkOrderActions();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const move = async (to: string) => {
    setBusy(true);
    setError(null);
    try {
      await setStatus(o.id, to);
    } catch (e) {
      setError(writeErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="space-y-1 border-b border-border/60 py-2 text-xs" data-testid={`order-${o.id}`} data-status={o.status}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-muted-foreground">#{o.id}</span>
        <span className="font-medium text-foreground">{o.title}</span>
        <span data-testid={`order-${o.id}-status`}>{ORDER_STATUS_LABEL[o.status]}</span>
        <span>Priority: {PRIORITY_LABEL[o.priority]}</span>
      </div>
      <p className="text-muted-foreground">
        {o.asset_external_id ? `Asset ${o.asset_external_id} · ` : ""}
        {originText(o)} · by {o.created_by}
        {o.assignee ? ` · assigned to ${o.assignee}` : ""}
      </p>
      {canWrite && o.next_statuses.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {o.next_statuses.map((s) => (
            <button key={s} type="button" className={BTN} disabled={busy} onClick={() => void move(s)} data-testid={`order-${o.id}-to-${s}`}>
              {ACTION_LABEL[s]}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive-text" data-testid={`order-${o.id}-error`}>{error}</p>
      )}
    </li>
  );
}

export function WorkOrdersPanel({ canWrite }: { canWrite: boolean }) {
  const [filter, setFilter] = useState<string>("");
  const { state, refetch } = useWorkOrders(filter || null);
  return (
    <section aria-labelledby="mx-orders" className="card-grid-glow space-y-3 rounded-lg p-4" data-testid="orders-panel">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 id="mx-orders" className="text-sm font-semibold text-foreground">Work orders</h2>
        <label className="space-y-1 text-xs">
          <span className="block font-medium text-foreground">Show</span>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">All</option>
            {ORDER_STATUSES.map((s) => (
              <option key={s} value={s}>{ORDER_STATUS_LABEL[s]}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-[11px] text-muted-foreground">A work order is a record. TwinGrid dispatches nothing and changes no equipment.</p>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading work orders…", empty: filter ? "No work orders with that status." : "No work orders yet." }}>
        {(rows) => (
          <ul data-testid="orders-list">
            {rows.map((o) => (
              <OrderRow key={o.id} o={o} canWrite={canWrite} />
            ))}
          </ul>
        )}
      </StateBoundary>
    </section>
  );
}
