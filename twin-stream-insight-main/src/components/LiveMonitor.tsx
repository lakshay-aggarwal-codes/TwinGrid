import { Zap, Droplets, Thermometer, Gauge, Wind, Activity } from 'lucide-react';
import { KpiCard } from './KpiCard';
import { AnomalyGauge } from './AnomalyGauge';
import { EventLog } from './EventLog';
import { FloorHeatmap } from './FloorHeatmap';
import { AnomalyAlert } from './AnomalyAlert';
import type { KpiData, EventItem } from '@/hooks/useSimulation';

interface Props {
  kpi: KpiData;
  anomalyScore: number;
  events: EventItem[];
  serverUtil: number;
  outsideTemp: number;
}

export function LiveMonitor({ kpi, anomalyScore, events, serverUtil, outsideTemp }: Props) {
  return (
    <div className="space-y-4">
      <AnomalyAlert anomalyScore={anomalyScore} />

      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="PUE" value={kpi.pue} trend={kpi.pueTrend} icon={Activity} color="text-primary" />
        <KpiCard label="WUE" value={kpi.wue} unit="L/kWh" icon={Droplets} color="text-chart-blue" />
        <KpiCard label="IT Power" value={kpi.itPowerKw} unit="kW" icon={Zap} color="text-chart-orange" />
        <KpiCard label="Cooling Power" value={kpi.coolingPowerKw} unit="kW" icon={Wind} color="text-chart-cyan" />
        <KpiCard label="Outlet Temp" value={kpi.outletTemp} unit="°C" icon={Thermometer} color="text-chart-red" />
        <KpiCard label="Water / Hour" value={kpi.waterPerHour} unit="L/h" icon={Gauge} color="text-chart-green" />
      </div>

      <FloorHeatmap serverUtil={serverUtil} outsideTemp={outsideTemp} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <AnomalyGauge score={anomalyScore} />
        <EventLog events={events} />
      </div>
    </div>
  );
}
