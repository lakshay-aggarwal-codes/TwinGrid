import { useState, useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import type { LatestAnomaly } from '@/hooks/useSimulation';

interface Props {
  anomalyScore: number;
  /**
   * The real anomaly type/message from the backend's trained detector
   * (/api/anomaly_score). Null if the score is elevated but no alert
   * payload has arrived yet (e.g. the rolling 12-reading buffer hasn't
   * filled) -- in that case this shows a generic, honest label rather
   * than guessing a category (see the Stage 0 audit: a previous version
   * of this component picked one at random on a timer).
   */
  anomaly: LatestAnomaly | null;
}

export function AnomalyAlert({ anomalyScore, anomaly }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const isActive = anomalyScore > 5;

  // un-dismiss when score changes significantly
   useEffect(() => {
     if (anomalyScore > 50) setDismissed(false);
  }, [anomalyScore]);

  if (!isActive || dismissed) return null;

  return (
    <div className="anomaly-alert-banner rounded-lg px-4 py-3 flex items-center gap-3 mb-4 border border-destructive/40 bg-destructive/10 backdrop-blur-sm">
      <div className="flex items-center gap-2 shrink-0">
        <AlertTriangle className="h-4 w-4 text-destructive animate-pulse" />
        <span className="text-xs font-bold uppercase tracking-wider text-destructive">Anomaly Detected</span>
      </div>
      <div className="h-4 w-px bg-destructive/30" />
      <div className="flex items-center gap-1.5 flex-1">
        <span className="text-sm text-foreground font-medium">
          {anomaly ? anomaly.type : 'Classifying…'}
        </span>
        {anomaly && <span className="text-sm text-muted-foreground">— {anomaly.message}</span>}
        <span className="text-sm text-muted-foreground">Score: <span className="font-mono text-destructive">{Math.round(anomalyScore)}%</span></span>
      </div>
      <button onClick={() => setDismissed(true)} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
