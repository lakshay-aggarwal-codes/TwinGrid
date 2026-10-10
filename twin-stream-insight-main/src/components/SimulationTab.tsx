import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { StateNotice } from '@/state/StateBoundary';
import { formatBackendNumber, type HourlyData, type SimInputs } from '@/hooks/useSimulation';
import { ChartFrame } from '@/components/charts/ChartFrame';

// Backend `cooling_mode` vocabulary -> display label + colour. A value not listed here is shown as unrecognised;
// it is never mapped to a known mode.
const MODES: Record<string, { label: string; color: string }> = {
  evaporative: { label: 'Evaporative', color: '#00E5FF' },
  closed_loop: { label: 'Closed-Loop', color: '#3B82F6' },
  free_air: { label: 'Free Air', color: '#22C55E' },
  hybrid: { label: 'Hybrid', color: '#F59E0B' },
};
const UNRECOGNISED = { label: 'Unrecognised mode', color: '#64748b' };
const modeOf = (raw: string) => (Object.prototype.hasOwnProperty.call(MODES, raw) ? MODES[raw] : UNRECOGNISED);

const LINE_COLUMNS = [
  { key: 'step', header: 'Step' },
  { key: 'it', header: 'IT power (kW)' },
  { key: 'cooling', header: 'Cooling power (kW)' },
  { key: 'outside', header: 'Outside temperature (°C)' },
];
const WATER_COLUMNS = [
  { key: 'step', header: 'Step' },
  { key: 'water', header: 'Water consumed (L)' },
  { key: 'mode', header: 'Cooling mode' },
];
const MODE_COLUMNS = [
  { key: 'mode', header: 'Cooling mode' },
  { key: 'steps', header: 'Steps' },
];

const RUN_VIEW = buildProvenance({ source: { kind: 'run-result' } });
const STEP_AXIS = 'step (hours from start of simulated run)';
const TOOLTIP_STYLE = { backgroundColor: 'hsl(213,50%,14%)', border: '1px solid hsl(213,30%,22%)', borderRadius: 8, color: '#e2e8f0' };

interface Props {
  data: HourlyData[];
  /** The settings the run was requested with; always shown beside the results. */
  inputs: SimInputs | null;
  /** The last run request failed. */
  failed?: boolean;
}

/** "Simulated run of 24 steps: mean utilisation 65 %, mean outside 22 °C, water stress 0.4." */
function inputsLine(i: SimInputs, steps: number): string {
  return `Simulated run of ${steps} steps (requested ${i.hours} h): mean utilisation ${i.meanUtilisationPct} %, mean outside ${i.meanOutsideTempC} °C, water stress ${i.waterStress}.`;
}

export function SimulationTab({ data, inputs, failed = false }: Props) {
  const failure = failed ? (
    <StateNotice kind="error" text="The last simulation request failed. Run it again from the sidebar." block />
  ) : null;

  if (!data.length) {
    return (
      <div className="space-y-3">
        {failure}
        <div className="flex items-center justify-center h-64 card-grid-glow rounded-lg">
          <p className="text-muted-foreground">Run a simulation from the sidebar to see results.</p>
        </div>
      </div>
    );
  }

  // The ONLY derived figure on this tab: the mean of the backend's hourly `pue`, labelled as a display aggregation.
  // Energy, water totals, CO2 and any "savings" are not provided by the backend for a run, so they are not shown.
  const meanPue = data.reduce((s, d) => s + d.pue, 0) / data.length;
  const tiles = [
    {
      label: 'Mean PUE',
      source: 'pue',
      value: formatBackendNumber('pue', meanPue),
      sub: 'mean of hourly backend PUE (display aggregation)',
    },
  ];

  const modeCounts: Record<string, number> = {};
  data.forEach((d) => {
    const label = modeOf(d.coolingMode).label;
    modeCounts[label] = (modeCounts[label] || 0) + 1;
  });
  const pieData = Object.entries(modeCounts).map(([name, value]) => ({
    name,
    value,
    color: (Object.values(MODES).find((m) => m.label === name) ?? UNRECOGNISED).color,
  }));
  const barData = data.map((d) => ({ ...d, modeColor: modeOf(d.coolingMode).color }));

  // FE-19 text alternatives: only backend values as provided (first/last step), counts of the rows returned, and the
  // simulated-not-live origin. Nothing is derived beyond the counts the pie already shows.
  const last = data[data.length - 1];
  const lineSummary =
    `Simulated run result, not live. ${data.length} steps, step ${data[0].step} to step ${last.step}. ` +
    `At step ${last.step}: IT power ${formatBackendNumber('it_power_kw', last.itPowerKw)} kW, ` +
    `cooling power ${formatBackendNumber('cooling_power_kw', last.coolingPowerKw)} kW, ` +
    `outside temperature ${formatBackendNumber('outside_temp_C', last.outsideTempC)} °C. The three series differ by line style.`;
  const lineRows = data.map((d) => ({
    step: d.step,
    it: formatBackendNumber('it_power_kw', d.itPowerKw),
    cooling: formatBackendNumber('cooling_power_kw', d.coolingPowerKw),
    outside: formatBackendNumber('outside_temp_C', d.outsideTempC),
  }));
  const waterSummary =
    `Simulated run result, not live. ${data.length} steps. At step ${last.step}: ${formatBackendNumber('water_consumed_L', last.waterConsumedL)} L. ` +
    `Bars are coloured by cooling mode; the data table names the mode of every step.`;
  const waterRows = data.map((d) => ({
    step: d.step,
    water: formatBackendNumber('water_consumed_L', d.waterConsumedL),
    mode: modeOf(d.coolingMode).label,
  }));
  const modeSummary =
    `Simulated run result, not live. ${data.length} steps by cooling mode: ` +
    pieData.map((d) => `${d.name} ${d.value}`).join(', ') +
    '.';
  const modeRows = pieData.map((d) => ({ mode: d.name, steps: d.value }));

  return (
    <div className="space-y-4">
      {failure}

      <div className="space-y-1">
        <ProvenanceStrip view={RUN_VIEW}>
          {inputs && (
            <span data-testid="run-inputs" className="text-xs text-foreground">
              {inputsLine(inputs, data.length)}
            </span>
          )}
        </ProvenanceStrip>
      </div>

      {/* Summary metrics: backend fields only. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="sim-tiles">
        {tiles.map((m) => (
          <div key={m.label} data-tile={m.label} data-source-field={m.source} className="card-grid-glow rounded-lg p-4 text-center">
            <span className="text-xs text-muted-foreground uppercase tracking-wider">{m.label}</span>
            <p className="text-xl font-bold font-mono text-foreground mt-1">{m.value}</p>
            <span className="text-[11px] text-muted-foreground">{m.sub}</span>
          </div>
        ))}
        <div data-testid="sim-not-provided" className="rounded-lg border border-dashed border-muted-foreground/50 p-4 text-xs text-muted-foreground">
          Not provided by the backend for a run: total energy, total water, CO₂, and any savings figure (a savings figure needs a
          backend baseline comparison).
        </div>
      </div>

      {/* Power + Temp line chart */}
      <ChartFrame
        title="Power & Temperature by simulated step"
        summary={lineSummary}
        columns={LINE_COLUMNS}
        rows={lineRows}
      >
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data} margin={{ bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(213,30%,22%)" />
            <XAxis
              dataKey="step"
              stroke="hsl(200,15%,55%)"
              tick={{ fontSize: 11 }}
              label={{ value: STEP_AXIS, position: 'insideBottom', offset: -12, style: { fill: 'hsl(200,15%,55%)', fontSize: 11 } }}
            />
            <YAxis yAxisId="power" stroke="hsl(200,15%,55%)" tick={{ fontSize: 11 }} label={{ value: 'kW', angle: -90, position: 'insideLeft', style: { fill: 'hsl(200,15%,55%)', fontSize: 11 } }} />
            <YAxis yAxisId="temp" orientation="right" stroke="hsl(200,15%,55%)" tick={{ fontSize: 11 }} label={{ value: '°C', angle: 90, position: 'insideRight', style: { fill: 'hsl(200,15%,55%)', fontSize: 11 } }} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12 }} />
            <Line yAxisId="power" type="monotone" dataKey="itPowerKw" name="IT Power" stroke="#F59E0B" strokeWidth={2} dot={false} />
            <Line yAxisId="power" type="monotone" dataKey="coolingPowerKw" name="Cooling Power" stroke="#00E5FF" strokeWidth={2} strokeDasharray="6 3" dot={false} />
            <Line yAxisId="temp" type="monotone" dataKey="outsideTempC" name="Outside Temp" stroke="#EF4444" strokeWidth={1.5} strokeDasharray="2 4" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartFrame>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Water: the backend field, as reported */}
        <ChartFrame
          title="Water consumed (L) — as reported per step"
          summary={waterSummary}
          columns={WATER_COLUMNS}
          rows={waterRows}
          note={
            <p className="text-[11px] text-muted-foreground mb-2">
              Backend field <code>water_consumed_L</code>, shown as provided (the twin accumulates it); not summed or derived here.
            </p>
          }
        >
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={barData} margin={{ bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(213,30%,22%)" />
              <XAxis
                dataKey="step"
                stroke="hsl(200,15%,55%)"
                tick={{ fontSize: 10 }}
                label={{ value: STEP_AXIS, position: 'insideBottom', offset: -12, style: { fill: 'hsl(200,15%,55%)', fontSize: 10 } }}
              />
              <YAxis stroke="hsl(200,15%,55%)" tick={{ fontSize: 10 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} itemStyle={{ color: '#e2e8f0' }} labelStyle={{ color: '#94a3b8' }} />
              <Bar dataKey="waterConsumedL" name="Water consumed (L)">
                {barData.map((d, i) => (
                  <Cell key={i} fill={d.modeColor} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartFrame>

        {/* Pie chart */}
        <ChartFrame
          title="Cooling mode by step (count of steps)"
          summary={modeSummary}
          columns={MODE_COLUMNS}
          rows={modeRows}
        >
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={3} dataKey="value">
                {pieData.map((d, i) => (
                  <Cell key={i} fill={d.color} />
                ))}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        </ChartFrame>
      </div>
    </div>
  );
}
