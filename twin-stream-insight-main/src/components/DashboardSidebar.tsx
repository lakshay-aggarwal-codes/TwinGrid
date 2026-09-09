import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Play, ChevronLeft, ChevronRight, Cpu, Thermometer, Droplets, Gauge, Loader2 } from 'lucide-react';
import type { SimConfig, CoolingMode } from '@/hooks/useSimulation';

interface Props {
  config: SimConfig;
  onChange: (c: SimConfig) => void;
  onRunSim: () => void;
  simRunning: boolean;
  collapsed: boolean;
  onToggle: () => void;
}

function SliderControl({ icon: Icon, label, value, min, max, step, unit, onChange, collapsed }: {
  icon: React.ElementType; label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void; collapsed: boolean;
}) {
  if (collapsed) return (
    <div className="flex flex-col items-center gap-1 py-2" title={`${label}: ${value}${unit}`}>
      <Icon className="h-4 w-4 text-primary" />
      <span className="text-[10px] font-mono text-muted-foreground">{value}</span>
    </div>
  );
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Icon className="h-3.5 w-3.5 text-primary" />{label}
        </Label>
        <span className="font-mono text-xs text-foreground">{value}{unit}</span>
      </div>
      <Slider min={min} max={max} step={step} value={[value]} onValueChange={([v]) => onChange(v)} className="[&_[role=slider]]:bg-primary [&_[role=slider]]:border-primary [&_.range]:bg-primary" />
    </div>
  );
}

export function DashboardSidebar({ config, onChange, onRunSim, simRunning, collapsed, onToggle }: Props) {
  const set = (partial: Partial<SimConfig>) => onChange({ ...config, ...partial });

  return (
    <aside className={`${collapsed ? 'w-16' : 'w-72'} transition-all duration-300 border-r border-border bg-sidebar flex flex-col shrink-0`}>
      <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between px-4'} py-3 border-b border-border`}>
        {!collapsed && <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Controls</span>}
        <button onClick={onToggle} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      <div className={`flex-1 overflow-y-auto ${collapsed ? 'px-2' : 'px-4'} py-4 space-y-4`}>
        <SliderControl icon={Cpu} label="Server Utilisation" value={config.serverUtil} min={10} max={100} step={1} unit="%" onChange={v => set({ serverUtil: v })} collapsed={collapsed} />
        <SliderControl icon={Thermometer} label="Outside Temperature" value={config.outsideTemp} min={-5} max={40} step={0.5} unit="°C" onChange={v => set({ outsideTemp: v })} collapsed={collapsed} />
        <SliderControl icon={Droplets} label="Water Stress Index" value={config.waterStress} min={0} max={1} step={0.05} unit="" onChange={v => set({ waterStress: +v.toFixed(2) })} collapsed={collapsed} />
        <SliderControl icon={Gauge} label="Chilled Water Setpoint" value={config.chilledWaterSetpoint} min={5} max={15} step={0.5} unit="°C" onChange={v => set({ chilledWaterSetpoint: v })} collapsed={collapsed} />

        {!collapsed && (
          <>
            <Separator className="bg-border/50" />
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Cooling Mode</Label>
              <Select value={config.coolingMode} onValueChange={(v) => set({ coolingMode: v as CoolingMode })}>
                <SelectTrigger className="bg-muted border-border text-foreground text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['Auto', 'Evaporative', 'Closed-Loop', 'Free Air', 'Hybrid'].map(m => (
                    <SelectItem key={m} value={m}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">AI Optimizer</Label>
              <Switch checked={config.aiOptimizer} onCheckedChange={v => set({ aiOptimizer: v })} />
            </div>

            <Separator className="bg-border/50" />

            <Button onClick={onRunSim} disabled={simRunning} className="w-full gap-2">
              {simRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {simRunning ? 'Simulating…' : 'Run 24h Simulation'}
            </Button>
          </>
        )}
      </div>
    </aside>
  );
}
