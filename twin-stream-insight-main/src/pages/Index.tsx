import { useMemo, useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Monitor, BarChart3, GitBranch, Leaf } from 'lucide-react';
import { DashboardHeader } from '@/components/DashboardHeader.tsx';
import { DashboardSidebar } from '@/components/DashboardSidebar';
import { LiveMonitor } from '@/components/LiveMonitor';
import { SimulationTab } from '@/components/SimulationTab';
import { WhatIfTab } from '@/components/WhatIfTab';
import { SustainabilityTab } from '@/components/SustainabilityTab.tsx';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useSharedSimulation } from '@/hooks/simulationContext';
import { useFeed } from '@/telemetry/useFeed';
import { useApiQuery } from '@/state/useApiQuery';
import { fetchEquipmentHealth } from '@/api/apiClient';
import type { LiveFeed } from '@/three/visualizationModes';
import { Slot } from '@/features/Slot';

const Index = () => {
  usePageTitle('TwinGrid — Analytics');
  const {
    config, setConfig, previewKpi, retryPreview, events, hourlyData, simInputs, simError, simRunning,
    runSimulation,
  } = useSharedSimulation();
  // FE-08: the stamped feed (frame + current freshness) for the header and the sustainability readings.
  const frame = useFeed((v) => v.frame);
  const freshness = useFeed((v) => v.freshness);
  const reconnectAttempt = useFeed((v) => v.transport.detail?.attempt ?? null);
  const feed: LiveFeed = useMemo(() => ({ frame, freshness, reconnectAttempt }), [frame, freshness, reconnectAttempt]);
  // FE-08: equipment health is a REST payload: loading / error / unavailable are explicit states, never silent omission.
  const equipment = useApiQuery({
    queryKey: ['equipment-health'],
    queryFn: ({ signal }) => fetchEquipmentHealth(signal),
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <DashboardHeader feed={feed} />
      <div className="flex flex-1 overflow-hidden">
        <DashboardSidebar
          config={config}
          onChange={setConfig}
          onRunSim={runSimulation}
          simRunning={simRunning}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(p => !p)}
        />
        <main className="min-w-0 flex-1 overflow-y-auto p-3 sm:p-5">
          <Tabs defaultValue="live" className="space-y-4">
            <TabsList className="h-auto max-w-full flex-wrap justify-start bg-muted/50 border border-border">
              <TabsTrigger value="live" className="gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <Monitor className="h-3.5 w-3.5" />Live Monitor
              </TabsTrigger>
              <TabsTrigger value="sim" className="gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <BarChart3 className="h-3.5 w-3.5" />24h Simulation
              </TabsTrigger>
              <TabsTrigger value="whatif" className="gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <GitBranch className="h-3.5 w-3.5" />What-If Scenarios
              </TabsTrigger>
              <TabsTrigger value="sustainability" className="gap-1.5 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <Leaf className="h-3.5 w-3.5" />Sustainability
              </TabsTrigger>
            </TabsList>

            <TabsContent value="live">
              <LiveMonitor previewKpi={previewKpi} onRetryPreview={retryPreview} events={events} />
            </TabsContent>
            <TabsContent value="sim">
              <h2 className="sr-only">24-hour simulation</h2>
              <SimulationTab data={hourlyData} inputs={simInputs} failed={simError} />
            </TabsContent>
            <TabsContent value="whatif">
              <h2 className="sr-only">What-if scenarios</h2>
              <WhatIfTab baseConfig={config} />
            </TabsContent>
            <TabsContent value="sustainability">
              <h2 className="sr-only">Sustainability</h2>
              <SustainabilityTab feed={feed} equipmentHealth={equipment.state} onRetryEquipment={equipment.refetch} />
            </TabsContent>
          </Tabs>
          <Slot name="dashboard" className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" />
        </main>
      </div>
    </div>
  );
};

export default Index;
