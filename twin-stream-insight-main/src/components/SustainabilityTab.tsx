import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { StateResponse, EquipmentHealthResponse } from '@/api/apiClient';

interface Props {
  liveState: StateResponse | null;
  equipmentHealth: EquipmentHealthResponse | null;
}

export function SustainabilityTab({ liveState, equipmentHealth }: Props) {
return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Grid Carbon Intensity</CardTitle>
        </CardHeader>
        <CardContent>
          {liveState?.carbon_intensity_gco2_per_kwh !== undefined ? (
            <>
              <div className="text-2xl font-bold">
                {liveState.carbon_intensity_gco2_per_kwh.toFixed(0)} <span className="text-sm font-normal">gCO2/kWh</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Cooling emitted ~{liveState.carbon_gco2?.toFixed(0)} gCO2 this step
              </p>
              <p className="text-xs text-muted-foreground mt-2">
                Real diurnal average from Electricity Maps data, not a live grid feed.
              </p>x``
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Waiting for live data...</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Water Stress</CardTitle>
        </CardHeader>
        <CardContent>
          {liveState?.water_stress !== undefined ? (
            <>
              <div className="text-2xl font-bold">{(liveState.water_stress * 100).toFixed(0)}%</div>
              {liveState.drought_override_active ? (
                <Badge variant="destructive" className="mt-2">
                  Drought override active — forced to closed-loop cooling
                </Badge>
              ) : (
                <p className="text-xs text-muted-foreground mt-1">Below the 70% drought threshold</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Waiting for live data...</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Predictive Maintenance</CardTitle>
        </CardHeader>
        <CardContent>
          {equipmentHealth?.available ? (
            <>
              <div className="text-2xl font-bold">
                {equipmentHealth.mae_improvement_pct?.toFixed(0)}%{' '}
                <span className="text-sm font-normal">MAE improvement over baseline</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                LSTM MAE {equipmentHealth.lstm?.mae.toFixed(1)} vs. baseline {equipmentHealth.baseline?.mae.toFixed(1)}
              </p>
              <p className="text-xs text-muted-foreground mt-2">{equipmentHealth.dataset_caveat}</p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {equipmentHealth?.message ?? 'Loading...'}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}