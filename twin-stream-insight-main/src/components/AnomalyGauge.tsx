import { useContext } from 'react';
import { SimulationContext } from '@/hooks/simulationContext';
import { ANOMALY_ICONS, gaugeGeometry, toAnomalyView, type AnomalyView } from '@/telemetry/anomalyView.tsx';
import type { AnomalyStatusPayload } from '@/api/apiClient';

interface Props {
  /** Defaults to the shared live feed's `anomaly_status`. `undefined` = read the shared feed; `null` = none received. */
  status?: AnomalyStatusPayload | null;
}

const R = 75;
const C = 100;
const START = 0.75 * Math.PI;
const SWEEP = 1.5 * Math.PI;

function point(fraction: number, radius: number) {
  const a = START + fraction * SWEEP;
  return { x: C + radius * Math.cos(a), y: C + radius * Math.sin(a) };
}

function arc(from: number, to: number): string {
  const s = point(from, R);
  const e = point(to, R);
  const large = (to - from) * SWEEP > Math.PI ? 1 : 0;
  return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`;
}

function useStatus(prop: Props['status']): AnomalyStatusPayload | null {
  const ctx = useContext(SimulationContext);
  if (prop !== undefined) return prop;
  return ctx?.anomalyStatus ?? null;
}

/** Text first, drawing second: every fact the arc shows is also in the DOM (no canvas-only status). */
export function AnomalyGauge({ status }: Props) {
  const view: AnomalyView = toAnomalyView(useStatus(status));
  const geometry = gaugeGeometry(view);
  const Icon = ANOMALY_ICONS[view.icon];
  const marker = geometry ? { a: point(geometry.markerFraction, R - 12), b: point(geometry.markerFraction, R + 12) } : null;

  return (
    <section
      aria-label="Anomaly detector"
      data-anomaly-kind={view.kind}
      className={`card-grid-glow rounded-lg p-5 flex flex-col items-center justify-center gap-2 text-center ${view.flagged ? 'anomaly-flash-border motion-reduce:animate-none' : ''}`}
    >
      <svg viewBox="0 0 200 200" width={200} height={200} role="img" aria-label={`Detector gauge. ${view.srText}`} className="gauge-ring">
        <path d={arc(0, 1)} fill="none" stroke="hsl(213, 30%, 22%)" strokeWidth={12} strokeLinecap="round" />
        {geometry && geometry.fillFraction > 0 && (
          <path
            d={arc(0, geometry.fillFraction)}
            fill="none"
            stroke="currentColor"
            strokeWidth={12}
            strokeLinecap="round"
            strokeDasharray={view.kind === 'anomalous' ? '10 4' : undefined}
            className={view.kind === 'anomalous' ? 'text-destructive' : 'text-primary'}
          />
        )}
        {marker && <line data-testid="threshold-marker" x1={marker.a.x} y1={marker.a.y} x2={marker.b.x} y2={marker.b.y} stroke="currentColor" strokeWidth={3} className="text-foreground" />}
        {/* Icon shape in the middle: state is never colour-only. */}
        <foreignObject x={80} y={72} width={40} height={40}>
          <div className="flex h-full w-full items-center justify-center">
            <Icon aria-hidden="true" className="h-7 w-7" />
          </div>
        </foreignObject>
      </svg>

      <p className="text-sm font-semibold text-foreground" data-testid="anomaly-label">{view.label}</p>
      {view.readout && (
        <p className="font-mono text-xs text-foreground" data-testid="anomaly-readout">
          {view.readout}
          {geometry && <span className="sr-only"> The marker on the gauge is the detector threshold.</span>}
        </p>
      )}
      <p className="max-w-[16rem] text-[11px] text-muted-foreground">{view.explanation}</p>
      <ul className="text-[10px] text-muted-foreground space-y-0.5">
        <li>{view.provenance.trainedOnText}</li>
        <li>{view.provenance.modelVersionText}</li>
        <li>{view.provenance.originText}</li>
      </ul>
    </section>
  );
}
