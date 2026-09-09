import { useState, useEffect } from 'react';
import { AlertTriangle, X, Droplets, Thermometer, Zap } from 'lucide-react';

export type AnomalyType = 'Water Leak' | 'Thermal Spike' | 'Power Surge';

const ANOMALY_CONFIG: Record<AnomalyType, { icon: React.ElementType; color: string }> = {
  'Water Leak': { icon: Droplets, color: 'text-chart-blue' },
  'Thermal Spike': { icon: Thermometer, color: 'text-chart-red' },
  'Power Surge': { icon: Zap, color: 'text-chart-orange' },
};

const ANOMALY_TYPES: AnomalyType[] = ['Water Leak', 'Thermal Spike', 'Power Surge'];

interface Props {
  anomalyScore: number;
}

export function AnomalyAlert({ anomalyScore }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const [anomalyType, setAnomalyType] = useState<AnomalyType>('Thermal Spike');
  const isActive = anomalyScore > 5;

  // rotate anomaly type occasionally
  useEffect(() => {
    if (!isActive) return;
    const interval = setInterval(() => {
      setAnomalyType(ANOMALY_TYPES[Math.floor(Math.random() * ANOMALY_TYPES.length)]);
    }, 10000);
    return () => clearInterval(interval);
  }, [isActive]);

  // un-dismiss when score changes significantly
  useEffect(() => {
    if (anomalyScore > 50) setDismissed(false);
  }, [anomalyScore > 50]);

  if (!isActive || dismissed) return null;

  const cfg = ANOMALY_CONFIG[anomalyType];
  const Icon = cfg.icon;

  return (
    <div className="anomaly-alert-banner rounded-lg px-4 py-3 flex items-center gap-3 mb-4 border border-destructive/40 bg-destructive/10 backdrop-blur-sm">
      <div className="flex items-center gap-2 shrink-0">
        <AlertTriangle className="h-4 w-4 text-destructive animate-pulse" />
        <span className="text-xs font-bold uppercase tracking-wider text-destructive">Anomaly Detected</span>
      </div>
      <div className="h-4 w-px bg-destructive/30" />
      <div className="flex items-center gap-1.5 flex-1">
        <Icon className={`h-4 w-4 ${cfg.color}`} />
        <span className="text-sm text-foreground font-medium">{anomalyType}</span>
        <span className="text-sm text-muted-foreground">— Score: <span className="font-mono text-destructive">{Math.round(anomalyScore)}%</span></span>
      </div>
      <button onClick={() => setDismissed(true)} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
