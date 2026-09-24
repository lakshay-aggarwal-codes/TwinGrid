import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Monitor, BarChart3, GitBranch, Leaf } from 'lucide-react';
import { DashboardHeader } from '@/components/DashboardHeader';
import { DashboardSidebar } from '@/components/DashboardSidebar';
import { LiveMonitor } from '@/components/LiveMonitor';
import { SimulationTab } from '@/components/SimulationTab';
import { WhatIfTab } from '@/components/WhatIfTab';
import { SustainabilityTab } from '@/components/SustainabilityTab';
import { useSimulation } from '@/hooks/useSimulation';

const Index = () => {
  const {
    config, setConfig, kpi, anomalyScore, events, hourlyData, simRunning,
    runSimulation, liveState, equipmentHealth,
  } = useSimulation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <DashboardHeader />
      <div className="flex flex-1 overflow-hidden">
        <DashboardSidebar
          config={config}
          onChange={setConfig}
          onRunSim={runSimulation}
          simRunning={simRunning}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(p => !p)}
        />
        <main className="flex-1 overflow-y-auto p-5">
          <Tabs defaultValue="live" className="space-y-4">
            <TabsList className="bg-muted/50 border border-border">
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
              <LiveMonitor kpi={kpi} anomalyScore={anomalyScore} events={events} serverUtil={config.serverUtil} outsideTemp={config.outsideTemp} />
            </TabsContent>
            <TabsContent value="sim">
              <SimulationTab data={hourlyData} />
            </TabsContent>
            <TabsContent value="whatif">
              <WhatIfTab baseConfig={config} />
            </TabsContent>
            <TabsContent value="sustainability">
              <SustainabilityTab liveState={liveState} equipmentHealth={equipmentHealth} />
            </TabsContent>
          </Tabs>
        </main>
      </div>
    </div>
  );
};

export default Index;