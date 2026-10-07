import { Zap, Droplets, Thermometer, Wind, Activity } from 'lucide-react';
import { KpiCard } from './KpiCard';
import { AnomalyGauge } from './AnomalyGauge';
import { EventLog } from './EventLog';
import { AnomalyAlert } from './AnomalyAlert';
import { ProvenanceStrip, buildProvenance } from '@/provenance';
import { StateBoundary } from '@/state/StateBoundary';
import type { DataState } from '@/state/dataState';
import { formatBackendNumber, type EventItem, type PreviewKpi } from '@/hooks/useSimulation';
import { unitFor } from '@/contract/units';

interface Props {
  /** FE-08: the /api/state PREVIEW for the sidebar settings. Loading / error / ready; never a zero placeholder. */
  previewKpi: DataState<PreviewKpi>;
  onRetryPreview?: () => void;
  events: EventItem[];
}

const PREVIEW_VIEW = buildProvenance({ source: { kind: 'preview' } });

const unit = (field: string) => unitFor(field)?.unit ?? undefined;

/** "at utilisation 65 %, outside 22 °C, water stress 0.4, cooling mode Auto" -- the inputs the values answer for. */
function inputsLine(p: PreviewKpi): string {
  const i = p.provenance.inputs;
  return `At utilisation ${i.utilisationPct} %, outside ${i.outsideTempC} °C, water stress ${i.waterStress}, cooling mode ${i.coolingMode}.`;
}

export function LiveMonitor({ previewKpi, onRetryPreview, events }: Props) {
  return (
    <div className="space-y-4">
      <AnomalyAlert />

      {/* Visually separate from every live-feed reading: dashed border, its own heading, its own Preview badge. */}
      <section
        aria-labelledby="preview-kpi-heading"
        data-testid="preview-kpis"
        className="rounded-lg border border-dashed border-muted-foreground/50 p-3 space-y-3"
      >
        <div className="space-y-1">
          <h2 id="preview-kpi-heading" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Preview — KPIs for the sidebar settings
          </h2>
          <ProvenanceStrip view={PREVIEW_VIEW}>
            <span className="text-xs">Computed by the backend twin for these settings. This is not the live feed.</span>
            {previewKpi.status === 'ready' && (
              <span data-testid="preview-inputs" className="text-xs text-foreground">
                {inputsLine(previewKpi.data)}
              </span>
            )}
          </ProvenanceStrip>
        </div>

        <StateBoundary
          state={previewKpi}
          onRetry={onRetryPreview}
          messages={{ loading: 'Loading the first preview from the backend…' }}
        >
          {(p) => {
            const k = p.value;
            const f = formatBackendNumber;
            return (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <KpiCard field="pue" label="PUE" value={f('pue', k.pue)} unit={unit('pue')} icon={Activity} color="text-primary" />
                <KpiCard field="wue" label="WUE" value={f('wue', k.wue)} unit={unit('wue')} icon={Droplets} color="text-chart-blue" />
                <KpiCard field="it_power_kw" label="IT Power" value={f('it_power_kw', k.itPowerKw)} unit={unit('it_power_kw')} icon={Zap} color="text-chart-orange" />
                <KpiCard field="cooling_power_kw" label="Cooling Power" value={f('cooling_power_kw', k.coolingPowerKw)} unit={unit('cooling_power_kw')} icon={Wind} color="text-chart-cyan" />
                <KpiCard field="server_outlet_temp_C" label="Outlet Temp" value={f('server_outlet_temp_C', k.outletTempC)} unit={unit('server_outlet_temp_C')} icon={Thermometer} color="text-chart-red" />
                <KpiCard field="water_flow_lpm" label="Water flow" value={f('water_flow_lpm', k.waterFlowLpm)} unit={unit('water_flow_lpm')} icon={Droplets} color="text-chart-green" />
              </div>
            );
          }}
        </StateBoundary>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <AnomalyGauge />
        <div className="space-y-1">
          <EventLog events={events} />
          <p className="text-[11px] text-muted-foreground" data-testid="event-times-note">
            Event times are browser receipt times, not data times.
          </p>
        </div>
      </div>
    </div>
  );
}
