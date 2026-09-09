interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  icon: React.ReactNode;
  trend?: 'up' | 'down' | 'stable';
}

export function MetricCard({ title, value, unit, icon, trend }: MetricCardProps) {
  const trendColor = {
    up: 'text-red-400',
    down: 'text-green-400',
    stable: 'text-blue-400'
  };

  return (
    <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 hover:border-slate-600 transition-all">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-slate-400 text-sm font-medium mb-2">{title}</p>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white">
              {typeof value === 'number' ? value.toFixed(2) : value}
            </span>
            {unit && <span className="text-slate-400 text-sm">{unit}</span>}
          </div>
        </div>
        <div className={`p-3 rounded-lg bg-slate-700/50 ${trend ? trendColor[trend] : 'text-blue-400'}`}>
          {icon}
        </div>
      </div>
    </div>
  );
}
