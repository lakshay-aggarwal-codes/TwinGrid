import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { StatusMessage } from '@/components/shell/StatusMessage';
import { FreshnessChip, ProvenanceBadge, formatAge } from '@/provenance';
import { feedProvenance, noDataNotice, toReadout, type LiveFeed } from '@/three/visualizationModes';
import type { EquipmentHealthResponse } from '@/api/apiClient';

interface Props {
  /** FE-06: the stamped live feed. Values are current, "Last known" with their age, or replaced by a state notice. */
  feed: LiveFeed;
  equipmentHealth: EquipmentHealthResponse | null;
}

export function SustainabilityTab({ feed, equipmentHealth }: Props) {
  const readout = toReadout(feed);
  const view = feedProvenance(feed);
  const liveState = readout.mode === 'none' ? null : readout.state;
  const lastKnown = readout.mode === 'last-known';
  const notice = readout.mode === 'none' ? noDataNotice(readout.freshness) : null;
  const provenance = feed.frame ? <ProvenanceBadge view={view} /> : <FreshnessChip view={view} />;
  const valueClass = lastKnown ? 'text-muted-foreground' : '';
  const cardClass = lastKnown ? 'border-dashed border-muted-foreground/60' : '';
  const lastKnownLabel =
    readout.mode === 'last-known' ? (
      <p data-testid="last-known" className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
        Last known · {formatAge(readout.ageMs)}
      </p>
    ) : null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-readout={readout.mode}>
      <Card className={cardClass}>
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            {liveState?.carbon_data_is_real === true ? 'Grid Carbon Intensity' : 'Carbon Intensity (fallback)'}
          </CardTitle>
          {provenance}
        </CardHeader>
        <CardContent>
          {notice ? (
            <StatusMessage kind={notice.kind}>{notice.text}</StatusMessage>
          ) : liveState?.carbon_intensity_gco2_per_kwh !== undefined ? (
            <>
              {lastKnownLabel}
              <div className={`text-2xl font-bold ${valueClass}`}>
                {liveState.carbon_intensity_gco2_per_kwh.toFixed(0)} <span className="text-sm font-normal">gCO2/kWh</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Cooling emitted ~{liveState.carbon_gco2?.toFixed(0)} gCO2 this step
              </p>
              <p className="text-xs text-muted-foreground mt-2">
                {liveState.carbon_data_is_real === true
                  ? 'Real diurnal average from Electricity Maps data, not a live grid feed.'
                  : liveState.carbon_data_is_real === false
                  ? `Flat fallback ${liveState.carbon_intensity_gco2_per_kwh.toFixed(0)} gCO2/kWh — not real grid data (no Electricity Maps data loaded on the backend).`
                  : 'Data source not reported by the backend.'}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Carbon intensity not reported by the backend.</p>
          )}
        </CardContent>
      </Card>

      <Card className={cardClass}>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Live Water Stress</CardTitle>
          {provenance}
        </CardHeader>
        <CardContent>
          {notice ? (
            <StatusMessage kind={notice.kind}>{notice.text}</StatusMessage>
          ) : liveState?.water_stress !== undefined ? (
            <>
              {lastKnownLabel}
              <div className={`text-2xl font-bold ${valueClass}`}>{(liveState.water_stress * 100).toFixed(0)}%</div>
              <p className="text-xs text-muted-foreground mt-1">
                {lastKnown ? 'Last known facility reading' : 'Live facility reading'} — independent of the Water Stress Index slider (What-If only)
              </p>
              {liveState.drought_override_active ? (
                <Badge variant="destructive" className="mt-2">
                  Drought override active — forced to closed-loop cooling
                </Badge>
              ) : (
                <p className="text-xs text-muted-foreground mt-1">Below the 70% drought threshold</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Water stress not reported by the backend.</p>
          )}
        </CardContent>
      </Card>

      {equipmentHealth?.available ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Predictive Maintenance</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {equipmentHealth.mae_improvement_pct?.toFixed(0)}%{' '}
              <span className="text-sm font-normal">MAE improvement over baseline</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              LSTM MAE {equipmentHealth.lstm?.mae.toFixed(1)} vs. baseline {equipmentHealth.baseline?.mae.toFixed(1)}
            </p>
            <p className="text-xs text-muted-foreground mt-2">{equipmentHealth.dataset_caveat}</p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
