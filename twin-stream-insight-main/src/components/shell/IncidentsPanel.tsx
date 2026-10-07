import { useEffect } from "react";
import { X, FileText } from "lucide-react";
import { StateBoundary } from "@/state/StateBoundary";
import { useApiQuery } from "@/state/useApiQuery";
import { buildIncidentReport, type Report } from "@/reports/reports";
import { fetchAlerts, type AlertRecord } from "@/api/apiClient";
import { alertsQueryKey } from "@/api/alerts";
import { useAuth } from "@/hooks/useAuth";
import { AlertList } from "@/components/alerts/AlertList";
import type { Role } from "@/components/alerts/AlertRowItem";
import { usePageVisible } from "@/components/alerts/usePageVisible";
import type { LatestAnomaly } from "@/hooks/useSimulation";

interface IncidentsPanelProps {
  open: boolean;
  onClose: () => void;
  /** Frames the whole facility (Stage 12's "spatial focus"). There is no
   * per-rack equivalent here -- see the notice in each alert's evidence. */
  onFocusFacility: () => void;
  /** Bumping this (a new live detection) is used only to know it's worth refetching the persisted list. */
  latestAnomaly: LatestAnomaly | null;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

export const ALERTS_LIMIT = 50;
export const REFRESH_INTERVAL_MS = 15000;

/**
 * Alert lifecycle list (FE-12). Rows are exactly what GET /api/alerts returns: severity (icon + text), type, the backend's message
 * verbatim, time (UTC, "UTC assumed" when the backend sent no offset), origin / model version, the detector score (reconstruction
 * error, never a percentage), and who acknowledged. Operators can acknowledge (pending, then the server's row); viewers see state only.
 *
 * This is a list of BACKEND alerts. It is facility-wide: the backend does not attribute an alert to a rack or sensor, so nothing here
 * claims to, and no explanation text is generated.
 *
 * Polling (15 s) runs only while the panel is open AND the tab is visible.
 */
export function IncidentsPanel({ open, onClose, onFocusFacility, latestAnomaly, onGenerateReport }: IncidentsPanelProps) {
  const { role: authRole } = useAuth();
  // Only the exact backend value "operator" enables operator controls; any other (or unknown) role is view-only here.
  const role: Role = authRole === "operator" ? "operator" : "viewer";
  const visible = usePageVisible();
  const queryKey = alertsQueryKey(ALERTS_LIMIT);

  const { state, refetch } = useApiQuery<AlertRecord[]>({
    queryKey,
    queryFn: ({ signal }) => fetchAlerts(ALERTS_LIMIT, signal),
    enabled: open,
    refetchInterval: open && visible ? REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
    isEmpty: (rows) => rows.length === 0,
  });

  // A fresh live detection means the backend just persisted a new row -- refetch promptly rather than waiting for the next poll.
  useEffect(() => {
    if (open && latestAnomaly) refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, latestAnomaly]);

  if (!open) return null;

  return (
    <aside aria-label="Incidents" className="w-80 border-r border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Incidents</span>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Close incidents"
        >
          <X aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Alerts recorded by the backend's anomaly detector (GET /api/alerts) -- one detector score, type and message per detection, for the
          whole facility. Selecting one frames the facility overview; the backend doesn't attribute an alert to a specific rack, so there's no
          rack to zoom to.
        </p>

        <StateBoundary
          state={state}
          onRetry={refetch}
          messages={{ empty: "No alerts recorded. The backend has not recorded any anomaly detections yet." }}
        >
          {(alerts) => (
            <>
              <button
                onClick={() => onGenerateReport(buildIncidentReport(alerts))}
                className="w-full flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <FileText aria-hidden="true" className="h-3.5 w-3.5" /> Generate incident report ({alerts.length} alerts in the list)
              </button>
              <AlertList alerts={alerts} role={role} queryKey={queryKey} onSelect={() => onFocusFacility()} />
            </>
          )}
        </StateBoundary>
      </div>
    </aside>
  );
}
