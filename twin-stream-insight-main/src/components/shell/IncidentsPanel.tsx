import { useCallback, useEffect, useState } from "react";
import { X, ChevronDown, ChevronRight, CheckCircle2, FileText } from "lucide-react";
import { StatusMessage } from "./StatusMessage";
import { buildIncidentReport, type Report } from "@/reports/reports";
import { fetchAlerts, type AlertRecord } from "@/api/apiClient";
import type { LatestAnomaly } from "@/hooks/useSimulation";

interface IncidentsPanelProps {
  open: boolean;
  onClose: () => void;
  /** Frames the whole facility (Stage 12's "spatial focus"). There is no
   * per-rack equivalent here -- see the notice below the list. */
  onFocusFacility: () => void;
  /** Bumping this (a new live detection from useSimulation, Stage 6) is used
   * only to know it's worth refetching the persisted list -- its own
   * {type, message} fields aren't shown, since the fetched AlertRecord for
   * the same event carries the same info plus severity/id/timestamp. */
  latestAnomaly: LatestAnomaly | null;
  /** Stage 13: hands a freshly built report to the page-level viewer. */
  onGenerateReport: (report: Report) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; alerts: AlertRecord[] }
  | { status: "error"; message: string };

const REFRESH_INTERVAL_MS = 15000;

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "CRITICAL":
      return "bg-destructive/20 text-destructive border-destructive/40";
    case "WARNING":
      return "bg-warning/20 text-warning border-warning/40";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "Unknown time";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/**
 * Stage 12: a compact, real incident list.
 *
 * CRITICAL CONSTRAINT this component is built around: GET /api/alerts is
 * facility-aggregate -- one score/type/message per detection, for the whole
 * facility (confirmed in api/routes/anomaly_routes.py + models/db_models.py's
 * Alert table: there's no rack/equipment column, and Alert.sensor_reading_id,
 * the one column that *could* link an alert to a specific reading, is never
 * set by data_repository.save_alert). So this panel does NOT claim
 * "Event -> rack -> telemetry -> explanation" -- the honest chain it
 * delivers is Event -> (whole-facility framing) -> explanation, and every
 * value shown below is a field this exact API response actually returned,
 * never invented or backfilled from the current live state.
 */
export function IncidentsPanel({ open, onClose, onFocusFacility, latestAnomaly, onGenerateReport }: IncidentsPanelProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const load = useCallback(() => {
    fetchAlerts(50)
      .then((alerts) => setState({ status: "ready", alerts }))
      .catch((e: Error) => setState({ status: "error", message: e.message || "Failed to load alerts." }));
  }, []);

  // Initial load + light polling while the panel is open, so it reflects
  // new alerts without the user having to reopen it.
  useEffect(() => {
    if (!open) return;
    setState({ status: "loading" });
    load();
    const interval = setInterval(load, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [open, load]);

  // A fresh live detection (Stage 6's WS-driven anomaly loop) means the
  // backend just persisted a new row -- refetch promptly rather than
  // waiting for the next poll tick.
  useEffect(() => {
    if (open && latestAnomaly) load();
  }, [open, latestAnomaly, load]);

  if (!open) return null;

  const handleSelect = (alert: AlertRecord) => {
    setExpandedId((prev) => (prev === alert.id ? null : alert.id));
    onFocusFacility();
  };

  return (
    <aside aria-label="Incidents" className="w-80 border-r border-border bg-sidebar flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Incidents</span>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors" aria-label="Close incidents">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Real alerts from the trained anomaly detector (GET /api/alerts) -- one score/type/message
          per detection, for the whole facility. Selecting one frames the facility overview; the
          backend doesn't attribute an alert to a specific rack, so there's no rack to zoom to.
        </p>

        {state.status === "loading" && <StatusMessage kind="loading" block>Loading alerts…</StatusMessage>}

        {state.status === "error" && (
          <StatusMessage kind="error" action={{ label: "Retry", onClick: load }}>
            {state.message}
          </StatusMessage>
        )}

        {state.status === "ready" && state.alerts.length === 0 && (
          <StatusMessage kind="empty" block>
            No alerts recorded. The facility has had no anomaly detections yet.
          </StatusMessage>
        )}

        {state.status === "ready" && state.alerts.length > 0 && (
          <button
            onClick={() => onGenerateReport(buildIncidentReport(state.alerts))}
            className="w-full flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          >
            <FileText className="h-3.5 w-3.5" /> Generate incident report ({state.alerts.length} alerts)
          </button>
        )}

        {state.status === "ready" && state.alerts.length > 0 && (
          <ul className="space-y-1.5">
            {state.alerts.map((a) => {
              const isExpanded = expandedId === a.id;
              return (
                <li key={a.id} className="rounded-md border border-border overflow-hidden">
                  <button
                    onClick={() => handleSelect(a)}
                    className="w-full flex items-start gap-2 px-2.5 py-2 text-left hover:bg-muted/60 transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                    )}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className={`text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${severityBadgeClass(a.severity)}`}>
                          {a.severity}
                        </span>
                        <span className="text-[11px] font-mono text-foreground truncate">{a.type}</span>
                        {a.acknowledged && (
                          <CheckCircle2 className="h-3 w-3 text-success shrink-0" aria-label="Acknowledged" />
                        )}
                      </div>
                      <p className="text-xs text-foreground leading-snug">{a.message}</p>
                      <p className="text-[10px] text-muted-foreground font-mono">{formatTimestamp(a.created_at)}</p>
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="px-2.5 pb-2.5 pt-1 border-t border-border bg-muted/30 space-y-1.5">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Evidence
                      </p>
                      <div className="text-[11px] font-mono text-foreground space-y-0.5">
                        <div className="flex justify-between"><span className="text-muted-foreground">Score</span>{a.score.toFixed(4)}</div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Severity</span>{a.severity}</div>
                        <div className="flex justify-between"><span className="text-muted-foreground">Alert ID</span>#{a.id}</div>
                        {a.acknowledged && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Acknowledged by</span>
                            {a.acknowledged_by ?? "unknown"}
                          </div>
                        )}
                      </div>
                      <p className="text-[10px] text-muted-foreground leading-relaxed">
                        This is everything the backend recorded for this alert. It doesn't store a
                        facility-state snapshot at the time of the alert (no rack, no historical
                        outlet temp, power draw, or pressure reading is attached) -- only the score,
                        type, message and severity above. Current live readings aren't shown here
                        either, since they describe right now, not the moment of this alert.
                      </p>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
