import { useId, useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDot, HelpCircle, Info, Loader2, XOctagon } from 'lucide-react';
import { acknowledgeAlert } from '@/api/alerts';
import { isApiError, type AlertRecord } from '@/api/apiClient';
import { AuthRequiredError } from '@/authClient';
import { ERROR_COPY } from '@/state/errorCopy';
import { ProvenanceBadge } from '@/provenance';
import { alertProvenance, alertTime, attributionEvidence, lifecycleOf, scoreLabel, severityView, type SeverityIcon } from './alertModel';

const SEVERITY_ICON: Record<SeverityIcon, typeof Info> = { info: Info, warning: AlertTriangle, critical: XOctagon, unknown: HelpCircle };

const SEVERITY_CLASS: Record<SeverityIcon, string> = {
  critical: 'bg-destructive/20 text-destructive border-destructive/40 border-solid',
  warning: 'bg-warning/20 text-warning border-warning/40 border-dashed',
  info: 'bg-muted text-foreground border-border border-solid',
  unknown: 'bg-muted text-muted-foreground border-border border-dotted',
};

export type Role = 'viewer' | 'operator' | null;

interface AlertRowItemProps {
  alert: AlertRecord;
  role: Role;
  /** Query key to refresh after an acknowledge attempt (the server's row is what gets shown). */
  queryKey: readonly unknown[];
  onSelect: (alert: AlertRecord) => void;
}

function ackErrorText(e: unknown): string {
  if (e instanceof AuthRequiredError) return ERROR_COPY.unauthenticated.description;
  if (isApiError(e)) return ERROR_COPY[e.kind].description;
  return ERROR_COPY.network.description;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="text-right break-words">{children}</span>
    </div>
  );
}

/** One backend alert: lifecycle state, severity (icon + text), message verbatim, time, provenance, acknowledge. */
export function AlertRowItem({ alert: a, role, queryKey, onSelect }: AlertRowItemProps) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const client = useQueryClient();
  const sev = severityView(a.severity);
  const SevIcon = SEVERITY_ICON[sev.icon];
  const lifecycle = lifecycleOf(a);
  const created = alertTime(a.created_at);
  const ackAt = alertTime(a.acknowledged_at);
  const extra = attributionEvidence(a);
  const view = alertProvenance(a);

  // No optimistic update: pending -> server result. The list is refetched either way so the row shows what the server holds.
  const ack = useMutation({
    mutationFn: () => acknowledgeAlert(a.id),
    onSettled: () => client.invalidateQueries({ queryKey }),
  });

  const toggle = () => {
    setExpanded((v) => !v);
    onSelect(a);
  };

  return (
    <li className="rounded-md border border-border overflow-hidden" data-alert-id={a.id} data-lifecycle={lifecycle}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="w-full flex items-start gap-2 px-2.5 py-2 text-left hover:bg-muted/60 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {expanded ? <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" /> : <ChevronRight aria-hidden="true" className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span data-severity={sev.known ? sev.text : 'unknown'} className={`inline-flex items-center gap-1 text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${SEVERITY_CLASS[sev.icon]}`}>
              <SevIcon aria-hidden="true" className="h-3 w-3" />
              {sev.text}
            </span>
            <span className="text-[11px] font-mono text-foreground truncate">{a.type}</span>
            <span data-testid="lifecycle" className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
              {lifecycle === 'acknowledged' ? <CheckCircle2 aria-hidden="true" className="h-3 w-3 text-success" /> : <CircleDot aria-hidden="true" className="h-3 w-3" />}
              {lifecycle === 'acknowledged' ? 'Acknowledged' : 'New'}
            </span>
          </div>
          <p className="text-xs text-foreground leading-snug">{a.message}</p>
          <p className="text-[10px] text-muted-foreground font-mono" data-testid="alert-time">
            {created.reported ? created.text : `Time ${created.text}`}
          </p>
        </div>
      </button>

      <div className="px-2.5 pb-2 flex flex-wrap items-center gap-2">
        <ProvenanceBadge view={view} />
        {lifecycle === 'new' &&
          (role === 'operator' ? (
            <button
              type="button"
              onClick={() => ack.mutate()}
              disabled={ack.isPending}
              className="rounded border border-border px-2 py-0.5 text-[11px] hover:bg-muted/60 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {ack.isPending ? (
                <span role="status" className="inline-flex items-center gap-1">
                  <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin motion-reduce:animate-none" /> Acknowledging…
                </span>
              ) : (
                'Acknowledge'
              )}
            </button>
          ) : (
            <button type="button" disabled aria-disabled="true" title="Requires operator role" className="rounded border border-border px-2 py-0.5 text-[11px] opacity-60">
              Acknowledge — requires operator role
            </button>
          ))}
      </div>
      {ack.isError && (
        <p role="alert" data-testid="ack-error" className="px-2.5 pb-2 text-[11px] text-destructive">
          Could not acknowledge alert #{a.id}: {ackErrorText(ack.error)}
        </p>
      )}

      {expanded && (
        <div id={panelId} className="px-2.5 pb-2.5 pt-1 border-t border-border bg-muted/30 space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Evidence</p>
          <div className="text-[11px] font-mono text-foreground space-y-0.5">
            <Field label="Alert ID">#{a.id}</Field>
            <Field label="Type">{a.type}</Field>
            <Field label="Severity">{sev.text}</Field>
            <Field label="Detector score">{a.score.toFixed(4)}</Field>
            <Field label="Time (created)">{created.text}</Field>
            <Field label="Origin">{a.origin ? a.origin : 'not reported (Unverified source)'}</Field>
            <Field label="Model version">{a.model_version ? a.model_version : 'not reported'}</Field>
            <Field label="Episode key">{a.dedupe_key ? a.dedupe_key : 'not reported'}</Field>
            {lifecycle === 'acknowledged' && (
              <>
                <Field label="Acknowledged by">{a.acknowledged_by ?? 'not reported'}</Field>
                <Field label="Acknowledged at">{ackAt.text}</Field>
              </>
            )}
            {extra.map((e) => (
              <Field key={e.field} label={e.field}>
                {e.value}
              </Field>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">{scoreLabel(a.score)}. This is the detector's reconstruction error, not a probability or a percentage.</p>
          {extra.length === 0 && (
            <p className="text-[10px] text-muted-foreground leading-relaxed" data-testid="no-attribution">
              Facility-wide; no sensor attribution. The backend does not attribute this alert to a rack or sensor and stores no facility-state snapshot with it, so
              no temperatures, power draw or rack are shown, and current live readings are deliberately not substituted.
            </p>
          )}
        </div>
      )}
    </li>
  );
}
