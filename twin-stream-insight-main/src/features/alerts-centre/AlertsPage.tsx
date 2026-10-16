import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useRole } from "@/hooks/useAuth";
import { usePageTitle } from "@/hooks/usePageTitle";
import { StateBoundary } from "@/state/StateBoundary";
import { AlertDetail } from "./AlertDetail";
import { AlertList } from "./AlertList";
import { alertsInboxKey } from "./api";
import { runBulk, type BulkResult } from "./bulk";
import { Filters } from "./Filters";
import { ExportButtons } from "../reports-export/ExportButtons";
import { ShareLinkButton } from "../reports-export/ShareLinkButton";
import { ALERT_EXPORT_COLUMNS } from "./exportColumns";
import {
  BULK_MAX,
  INBOX_LIMIT,
  NO_FILTERS,
  applyFilters,
  bulkAckTargets,
  countAlerts,
  parseAlertParam,
  selectableOpenIds,
  toggleSelected,
  withAlertParam,
  type Filters as FilterState,
  type InboxAlert,
} from "./model";
import { readSoundPref, writeSoundPref } from "./prefs";
import { useAlertActions } from "./useAlertActions";
import { useInbox } from "./useInbox";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function bulkSummary(r: BulkResult): string {
  const parts = [`${r.done.length} acknowledged`];
  if (r.failed.length) parts.push(`${r.failed.length} failed`);
  if (r.skipped.length) parts.push(`${r.skipped.length} not attempted`);
  return `${parts.join(", ")}.`;
}

function Inbox({ alerts }: { alerts: readonly InboxAlert[] }) {
  const { isOperator } = useRole();
  const apply = useAlertActions();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const selectedId = parseAlertParam(`?${params.toString()}`);
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [selection, setSelection] = useState<ReadonlySet<number>>(new Set());
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  const visible = useMemo(() => applyFilters(alerts, filters), [alerts, filters]);
  const counts = useMemo(() => countAlerts(alerts), [alerts]);
  const selected = alerts.find((a) => a.id === selectedId) ?? null;
  const targets = bulkAckTargets(selection, alerts);
  const running = progress !== null;

  // A selection never outlives the alert being open: drop ids that were acknowledged elsewhere.
  useEffect(() => {
    setSelection((prev) => {
      const keep = new Set([...prev].filter((id) => alerts.some((a) => a.id === id && a.status === "open")));
      return keep.size === prev.size ? prev : keep;
    });
  }, [alerts]);

  function select(id: number) {
    setParams(withAlertParam(`?${params.toString()}`, id).replace(/^\?/, ""), { replace: true });
  }

  async function acknowledgeSelected() {
    setBulkMessage(null);
    setProgress({ done: 0, total: targets.length });
    const result = await runBulk(targets, (id) => apply(id, { status: "acknowledged" }), (done, total) => setProgress({ done, total }));
    setProgress(null);
    setSelection(new Set());
    setBulkMessage(bulkSummary(result));
    void client.invalidateQueries({ queryKey: alertsInboxKey });
  }

  return (
    <div className="space-y-4">
      <p data-testid="alert-counts" className="text-sm text-muted-foreground">
        {counts.total} alerts (latest {INBOX_LIMIT} at most): {counts.open} open, {counts.acknowledged} acknowledged, {counts.resolved} resolved.{" "}
        <strong className="text-foreground">{counts.openCritical} open critical.</strong>
      </p>

      <Filters value={filters} onChange={setFilters} />

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Export and share">
        <ExportButtons label="alerts" columns={ALERT_EXPORT_COLUMNS} rows={visible} />
        <ShareLinkButton />
      </div>

      {isOperator ? (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Bulk acknowledge">
          <button type="button" className={BTN} disabled={running} onClick={() => setSelection(new Set(selectableOpenIds(visible)))}>
            Select open alerts (up to {BULK_MAX})
          </button>
          <button type="button" className={BTN} disabled={running || selection.size === 0} onClick={() => setSelection(new Set())}>
            Clear selection
          </button>
          <button type="button" className={BTN} disabled={running || targets.length === 0} onClick={() => void acknowledgeSelected()}>
            Acknowledge {targets.length} selected
          </button>
          <span role="status" aria-live="polite" className="text-xs text-muted-foreground">
            {progress ? `Acknowledging ${progress.done} of ${progress.total}…` : bulkMessage}
          </span>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0">
          {visible.length === 0 ? (
            <p data-testid="no-matches" className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              No alerts match these filters. Clear a filter to see more.
            </p>
          ) : (
            <AlertList
              alerts={visible}
              selectedId={selectedId}
              onSelect={select}
              canSelect={isOperator}
              selection={selection}
              onToggle={(id) => setSelection((s) => toggleSelected(s, id))}
            />
          )}
        </div>
        <div className="min-w-0">
          {selected ? (
            <AlertDetail key={selected.id} alert={selected} isOperator={isOperator} apply={apply} />
          ) : (
            <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              {selectedId !== null ? `Alert ${selectedId} is not in the latest ${INBOX_LIMIT} alerts.` : "Select an alert to see its details and timeline."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AlertsPage() {
  usePageTitle("Alerts centre · TwinGrid");
  const { state, refetch } = useInbox();
  const [sound, setSound] = useState(() => readSoundPref());
  return (
    <main aria-labelledby="alerts-heading" className="mx-auto max-w-7xl space-y-4 p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 id="alerts-heading" className="text-lg font-semibold">
            Alerts centre
          </h1>
          <p className="max-w-prose text-xs text-muted-foreground">
            Alerts raised by the anomaly detector, with their lifecycle (open, acknowledged, resolved), assignee and notes. Each alert shows the data origin it was raised on.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={sound}
            className="h-4 w-4 accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onChange={(e) => {
              setSound(e.target.checked);
              writeSoundPref(e.target.checked);
            }}
          />
          Play a sound for new critical alerts (off by default)
        </label>
      </header>
      <StateBoundary state={state} onRetry={refetch} messages={{ empty: "No alerts have been recorded yet." }}>
        {(alerts) => <Inbox alerts={alerts} />}
      </StateBoundary>
    </main>
  );
}
