import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface Props {
  label: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'stable';
  icon: React.ElementType;
  color?: string;
}

export function KpiCard({ label, value, unit, trend, icon: Icon, color = 'text-primary' }: Props) {
  return (
    <div className="card-grid-glow rounded-lg p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
        <Icon className={`h-4 w-4 ${color} opacity-60`} />
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-bold font-mono text-foreground">{value}</span>
        {unit && <span className="text-sm text-muted-foreground mb-0.5">{unit}</span>}
        {trend && (
          <span className={`ml-auto ${trend === 'down' ? 'text-success' : trend === 'up' ? 'text-warning' : 'text-muted-foreground'}`}>
            {trend === 'down' ? <TrendingDown className="h-4 w-4" /> : trend === 'up' ? <TrendingUp className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
          </span>
        )}
      </div>
    </div>
  );
}
