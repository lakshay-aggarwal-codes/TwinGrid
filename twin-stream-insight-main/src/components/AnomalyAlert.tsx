import { useContext, useEffect, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { SimulationContext } from '@/hooks/simulationContext';
import { toAnomalyView } from '@/telemetry/anomalyView';
import type { AnomalyStatusPayload } from '@/api/apiClient';

interface Props {
  /** Defaults to the shared live feed's `anomaly_status`. */
  status?: AnomalyStatusPayload | null;
}

/**
 * The banner exists ONLY while the backend says `status === 'anomalous'`. It never appears for warming up,
 * unavailable, error or unknown states (those are shown by the gauge / console as their own states).
 * A new anomaly episode (the server's `dedupe_key`) un-dismisses it. The episode start is announced once.
 */
export function AnomalyAlert({ status }: Props) {
  const ctx = useContext(SimulationContext);
  const payload = status !== undefined ? status : (ctx?.anomalyStatus ?? null);
  const view = toAnomalyView(payload);
  const [dismissed, setDismissed] = useState(false);
  const episodeKey = payload?.episode?.dedupe_key ?? null;

  useEffect(() => {
    setDismissed(false);
  }, [episodeKey]);

  useEffect(() => {
    if (!view.flagged) setDismissed(false); // a later anomaly after recovery is shown again
  }, [view.flagged]);

  if (!view.flagged || dismissed) return null;

  return (
    <div
      role="alert"
      data-anomaly-kind="anomalous"
      className="anomaly-alert-banner rounded-lg px-4 py-3 flex items-center gap-3 mb-4 border border-destructive/40 bg-destructive/10 backdrop-blur-sm"
    >
      <div className="flex items-center gap-2 shrink-0">
        <AlertTriangle aria-hidden="true" className="h-4 w-4 text-destructive animate-pulse motion-reduce:animate-none" />
        <span className="text-xs font-bold uppercase tracking-wider text-destructive">{view.label}</span>
      </div>
      <div className="h-4 w-px bg-destructive/30" />
      <div className="flex flex-wrap items-center gap-x-1.5 flex-1 text-sm">
        {view.type && <span className="text-foreground font-medium">{view.type}</span>}
        {view.message && <span className="text-muted-foreground">— {view.message}</span>}
        {view.readout && <span className="font-mono text-xs text-muted-foreground">{view.readout}</span>}
        <span className="text-[11px] text-muted-foreground">{view.provenance.trainedOnText}</span>
      </div>
      <button
        type="button"
        aria-label="Dismiss anomaly banner"
        onClick={() => setDismissed(true)}
        className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
      >
        <X aria-hidden="true" className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
