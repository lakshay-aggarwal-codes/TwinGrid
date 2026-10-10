import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from 'recharts';
import { classifyOrigin } from '@/provenance';
import { originForProvenance } from '@/telemetry/history/origin';
import { formatUtc, formatValue, qualityLabel, type ChartModel, type HistoryPoint } from '@/telemetry/history/model';

/** Most excluded-sample markers drawn on the chart. All of them stay listed in the data table. */
export const MAX_EXCLUDED_MARKS = 200;
/** Above this many valid points the per-point dots are dropped (the line remains). Never downsampled. */
export const DOT_LIMIT = 300;

interface PlotProps {
  model: ChartModel;
  unit: string | null;
  /** Requested window, epoch ms. */
  domain: readonly [number, number];
  /** Injected by ResponsiveContainer; set explicitly in tests. */
  width?: number;
  height?: number;
}

function PointTooltip({ active, payload, unit }: TooltipProps<number, string> & { unit: string | null }) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload as HistoryPoint | undefined;
  if (!p || p.gapBreak || p.v === null) return null;
  return (
    <div className="rounded border border-border bg-popover p-2 text-xs text-popover-foreground shadow" data-testid="history-tooltip">
      <div>{p.iso} (event time, UTC)</div>
      <div>{formatValue(p.v, unit)}</div>
      <div>Origin: {classifyOrigin(originForProvenance(p.origin)).text}</div>
      <div>Quality: {qualityLabel(p.quality)}</div>
    </div>
  );
}

const tick = (ms: number) => formatUtc(ms).slice(5, 16);

/**
 * The plot. Gaps are the backend's `/gaps` entries: the line is broken (a `v: null` point) and a hatched band labelled
 * "gap" covers the span. Nothing is interpolated across them. Invalid / unrecognised samples are marked by dashed /
 * dotted vertical lines at their event time; their values are not plotted.
 */
export function HistoryPlot({ model, unit, domain, width, height = 280 }: PlotProps) {
  const marks = model.excluded.slice(0, MAX_EXCLUDED_MARKS);
  const dots = model.goodCount <= DOT_LIMIT;
  return (
    <LineChart width={width} height={height} data={model.line as HistoryPoint[]} margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
      <defs>
        <pattern id="history-gap-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="currentColor" strokeWidth="2" />
        </pattern>
      </defs>
      <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
      <XAxis
        type="number"
        dataKey="t"
        domain={[domain[0], domain[1]]}
        scale="time"
        tickFormatter={tick}
        tick={{ fontSize: 11 }}
        label={{ value: 'Event time (UTC, from the backend)', position: 'insideBottom', offset: -12, fontSize: 11 }}
      />
      <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }} width={56} label={{ value: unit ?? 'unit not reported', angle: -90, position: 'insideLeft', fontSize: 11 }} />
      {model.gapBands.map((g) => (
        <ReferenceArea
          key={`gap-${g.x1}-${g.x2}`}
          x1={g.x1}
          x2={g.x2}
          fill="url(#history-gap-hatch)"
          fillOpacity={0.35}
          stroke="currentColor"
          strokeDasharray="2 2"
          ifOverflow="hidden"
          label={{ value: 'gap', position: 'insideTop', fontSize: 10 }}
        />
      ))}
      {marks.map((p, i) => (
        <ReferenceLine
          key={`x-${p.t}-${i}`}
          x={p.t}
          stroke="currentColor"
          strokeWidth={1.5}
          strokeDasharray={p.quality === 'invalid' ? '5 3' : '1 3'}
          ifOverflow="hidden"
        />
      ))}
      <Tooltip content={<PointTooltip unit={unit} />} isAnimationActive={false} />
      <Line type="linear" dataKey="v" stroke="hsl(var(--primary))" strokeWidth={2} dot={dots ? { r: 3 } : false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />
    </LineChart>
  );
}

export function HistoryChart(props: Omit<PlotProps, 'width' | 'height'>) {
  return (
    <div className="h-[280px] w-full text-muted-foreground" data-testid="history-chart">
      <ResponsiveContainer width="100%" height="100%">
        <HistoryPlot {...props} />
      </ResponsiveContainer>
    </div>
  );
}
