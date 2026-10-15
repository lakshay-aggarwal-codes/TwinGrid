import { formatUtc, type InboxAlert } from "./model";
import { SeverityBadge, StatusBadge } from "./badges";

interface Props {
  alerts: readonly InboxAlert[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Operators get a checkbox per row (open alerts only) for bulk acknowledge. */
  canSelect: boolean;
  selection: ReadonlySet<number>;
  onToggle: (id: number) => void;
}

export function AlertList({ alerts, selectedId, onSelect, canSelect, selection, onToggle }: Props) {
  return (
    <ul aria-label="Alerts" className="divide-y divide-border rounded-md border border-border bg-card">
      {alerts.map((a) => {
        const selected = a.id === selectedId;
        return (
          <li key={a.id} data-testid="alert-row" data-alert-id={a.id} className={`flex items-start gap-2 p-2 ${selected ? "bg-muted/60" : ""}`}>
            {canSelect && (
              <input
                type="checkbox"
                className="mt-1.5 h-4 w-4 shrink-0 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`Select alert ${a.id} for bulk acknowledge`}
                checked={selection.has(a.id)}
                disabled={a.status !== "open"}
                title={a.status === "open" ? undefined : "Only open alerts can be acknowledged in bulk"}
                onChange={() => onToggle(a.id)}
              />
            )}
            <button
              type="button"
              onClick={() => onSelect(a.id)}
              aria-current={selected ? "true" : undefined}
              className="min-w-0 flex-1 rounded p-1 text-left hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex flex-wrap items-center gap-1.5">
                <SeverityBadge severity={a.severity} />
                <StatusBadge status={a.status} />
                <span className="text-[11px] text-muted-foreground">#{a.id}</span>
              </span>
              <span className="mt-1 block break-words text-sm text-foreground">{a.message}</span>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">
                {formatUtc(a.created_at)}
                {a.assignee ? ` · assigned to ${a.assignee}` : " · unassigned"}
                {a.origin ? ` · origin: ${a.origin}` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
