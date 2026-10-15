import { AlertTriangle, CheckCircle2, CircleDot, HelpCircle, Info, UserCheck, XOctagon, type LucideIcon } from "lucide-react";
import { severityView, type SeverityIcon } from "@/components/alerts/alertModel";
import { STATUS_LABEL, type AlertStatus } from "./model";

const SEVERITY_ICON: Record<SeverityIcon, LucideIcon> = { info: Info, warning: AlertTriangle, critical: XOctagon, unknown: HelpCircle };
// Meaning is carried by the icon SHAPE, the text and the border style (solid / dashed / dotted), not by colour alone.
const SEVERITY_CLASS: Record<SeverityIcon, string> = {
  critical: "bg-destructive/20 text-destructive border-destructive/40 border-solid",
  warning: "bg-warning/20 text-warning border-warning/40 border-dashed",
  info: "bg-muted text-foreground border-border border-solid",
  unknown: "bg-muted text-muted-foreground border-border border-dotted",
};

const STATUS_ICON: Record<AlertStatus, LucideIcon> = { open: CircleDot, acknowledged: UserCheck, resolved: CheckCircle2 };
const STATUS_CLASS: Record<AlertStatus, string> = {
  open: "border-solid border-foreground/40 text-foreground",
  acknowledged: "border-dashed border-foreground/40 text-foreground",
  resolved: "border-dotted border-muted-foreground/60 text-muted-foreground",
};

const BASE = "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide";

export function SeverityBadge({ severity }: { severity: string }) {
  const view = severityView(severity);
  const Icon = SEVERITY_ICON[view.icon];
  return (
    <span data-testid="severity-badge" data-severity={view.known ? view.text : "unknown"} className={`${BASE} ${SEVERITY_CLASS[view.icon]}`}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {view.text}
    </span>
  );
}

export function StatusBadge({ status }: { status: AlertStatus }) {
  const Icon = STATUS_ICON[status];
  return (
    <span data-testid="status-badge" data-status={status} className={`${BASE} ${STATUS_CLASS[status]}`}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {STATUS_LABEL[status]}
    </span>
  );
}
