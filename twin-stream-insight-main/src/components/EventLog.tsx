import { AlertCircle, CheckCircle, Info, AlertTriangle } from 'lucide-react';
import type { EventItem } from '@/hooks/useSimulation';

const iconMap = {
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
  error: AlertCircle,
};
const colorMap = {
  info: 'text-chart-blue',
  success: 'text-success',
  warning: 'text-warning',
  error: 'text-destructive',
};

export function EventLog({ events }: { events: EventItem[] }) {
  return (
    <div className="card-grid-glow rounded-lg p-4 space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">System Events</h3>
      <div className="space-y-2">
        {events.map(e => {
          const Icon = iconMap[e.type];
          return (
            <div key={e.id} className="flex items-start gap-2 text-sm">
              <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${colorMap[e.type]}`} />
              <span className="text-foreground/90 flex-1">{e.message}</span>
              <span className="font-mono text-[11px] text-muted-foreground shrink-0">{e.time}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
