import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import type { HourlyData } from '@/hooks/useSimulation';

const MODE_COLORS: Record<string, string> = {
  'Evaporative': '#00E5FF',
  'Closed-Loop': '#3B82F6',
  'Free Air': '#22C55E',
  'Hybrid': '#F59E0B',
  'Auto': '#A78BFA',
};

interface Props {
  data: HourlyData[];
}

export function SimulationTab({ data }: Props) {
  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-64 card-grid-glow rounded-lg">
        <p className="text-muted-foreground">Run a 24h simulation from the sidebar to see results.</p>
      </div>
    );
  }

  const totalWater = data.reduce((s, d) => s + d.waterConsumed, 0);
  const baselineWater = totalWater * 1.35;
  const waterSaved = baselineWater - totalWater;
  const avgPue = (data.reduce((s, d) => s + (d.itPower + d.coolingPower + 40) / d.itPower, 0) / 24).toFixed(2);
  const totalEnergy = data.reduce((s, d) => s + d.itPower + d.coolingPower, 0);
  const co2Avoided = (totalEnergy * 0.4 * 0.25).toFixed(0);

  // pie data
  const modeCounts: Record<string, number> = {};
  data.forEach(d => { modeCounts[d.coolingMode] = (modeCounts[d.coolingMode] || 0) + 1; });
  const pieData = Object.entries(modeCounts).map(([name, value]) => ({ name, value }));

  return (
    <div className="space-y-4">
      {/* Summary metrics */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Water Saved', value: `${waterSaved.toFixed(0)} L`, sub: 'vs baseline' },
          { label: 'Avg PUE', value: avgPue, sub: '24h average' },
          { label: 'Total Energy', value: `${(totalEnergy / 1000).toFixed(1)} MWh`, sub: '24h total' },
          { label: 'CO₂ Avoided', value: `${co2Avoided} kg`, sub: 'estimated' },
        ].map(m => (
          <div key={m.label} className="card-grid-glow rounded-lg p-4 text-center">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">{m.label}</span>
            <p className="text-xl font-bold font-mono text-foreground mt-1">{m.value}</p>
            <span className="text-[11px] text-muted-foreground">{m.sub}</span>
          </div>
        ))}
      </div>

      {/* Power + Temp line chart */}
      <div className="card-grid-glow rounded-lg p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Power & Temperature — 24h</h3>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(213,30%,22%)" />
            <XAxis dataKey="hour" stroke="hsl(200,15%,55%)" tick={{ fontSize: 11 }} tickFormatter={h => `${h}:00`} />
            <YAxis yAxisId="power" stroke="hsl(200,15%,55%)" tick={{ fontSize: 11 }} label={{ value: 'kW', angle: -90, position: 'insideLeft', style: { fill: 'hsl(200,15%,55%)', fontSize: 11 } }} />
            <YAxis yAxisId="temp" orientation="right" stroke="hsl(200,15%,55%)" tick={{ fontSize: 11 }} label={{ value: '°C', angle: 90, position: 'insideRight', style: { fill: 'hsl(200,15%,55%)', fontSize: 11 } }} />
            <Tooltip contentStyle={{ backgroundColor: 'hsl(213,50%,14%)', border: '1px solid hsl(213,30%,22%)', borderRadius: 8, color: '#e2e8f0' }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line yAxisId="power" type="monotone" dataKey="itPower" name="IT Power" stroke="#F59E0B" strokeWidth={2} dot={false} />
            <Line yAxisId="power" type="monotone" dataKey="coolingPower" name="Cooling Power" stroke="#00E5FF" strokeWidth={2} dot={false} />
            <Line yAxisId="temp" type="monotone" dataKey="temperature" name="Ambient Temp" stroke="#EF4444" strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Water bar chart */}
        <div className="card-grid-glow rounded-lg p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Water Consumption by Hour</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(213,30%,22%)" />
              <XAxis dataKey="hour" stroke="hsl(200,15%,55%)" tick={{ fontSize: 10 }} tickFormatter={h => `${h}h`} />
              <YAxis stroke="hsl(200,15%,55%)" tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={{ backgroundColor: 'hsl(213,50%,14%)', border: '1px solid hsl(213,30%,22%)', borderRadius: 8, color: '#e2e8f0' }} itemStyle={{ color: '#e2e8f0' }} labelStyle={{ color: '#94a3b8' }} />
              <Bar dataKey="waterConsumed" name="Water (L)">
                {data.map((d, i) => (
                  <Cell key={i} fill={MODE_COLORS[d.coolingMode] || '#00E5FF'} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Pie chart */}
        <div className="card-grid-glow rounded-lg p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Cooling Mode Distribution</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                {pieData.map((d, i) => (
                  <Cell key={i} fill={MODE_COLORS[d.name] || '#00E5FF'} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ backgroundColor: 'hsl(213,50%,14%)', border: '1px solid hsl(213,30%,22%)', borderRadius: 8, color: '#e2e8f0' }} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
