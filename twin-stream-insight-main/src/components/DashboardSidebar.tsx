import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { useEffect } from 'react';
import { useIsMobile } from '@/hooks/use-mobile';
import { Play, ChevronLeft, ChevronRight, Cpu, Thermometer, Droplets, Gauge, Loader2 } from 'lucide-react';
import type { SimConfig, CoolingMode } from '@/hooks/useSimulation';
import { FeatureNav } from '@/features/FeatureNav';
import { useRole } from '@/hooks/useAuth';
import { OPERATOR_REQUIRED_TEXT, isReadOnly } from '@/roleAccess';

interface Props {
  config: SimConfig;
  onChange: (c: SimConfig) => void;
  onRunSim: () => void;
  simRunning: boolean;
  collapsed: boolean;
  onToggle: () => void;
}

function SliderControl({ icon: Icon, label, value, min, max, step, unit, onChange, collapsed, locked }: {
  icon: React.ElementType; label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void; collapsed: boolean; locked: boolean;
}) {
  if (collapsed) return (
    <div role="img" aria-label={`${label}: ${value}${unit}`} className="flex flex-col items-center gap-1 py-2" title={`${label}: ${value}${unit}`}>
      <Icon aria-hidden="true" className="h-4 w-4 text-primary" />
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
      <Slider aria-label={label} min={min} max={max} step={step} value={[value]} disabled={locked} aria-describedby={locked ? 'controls-locked-note' : undefined} onValueChange={([v]) => onChange(v)} className="[&_[role=slider]]:bg-primary [&_[role=slider]]:border-primary [&_.range]:bg-primary" />
    </div>
  );
}

export function DashboardSidebar({ config, onChange, onRunSim, simRunning, collapsed, onToggle }: Props) {
  // Viewers are read-only: every control that changes an input or starts a run is locked (visibly, with the reason). The values stay shown.
  // UX only; the server refuses what a viewer may not do.
  const { role } = useRole();
  const locked = isReadOnly(role);
  const set = (partial: Partial<SimConfig>) => {
    if (locked) return;
    onChange({ ...config, ...partial });
  };
  // Task 21: on phones an open sidebar is an overlay (a 288px column would leave ~70px for the page at 360px), a
  // closed one is a slim rail, and Escape closes the overlay.
  const mobile = useIsMobile();
  const overlay = mobile && !collapsed;
  useEffect(() => {
    if (!overlay) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onToggle();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [overlay, onToggle]);

  const width = overlay ? 'fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] shadow-elevation-3' : collapsed ? (mobile ? 'w-12' : 'w-16') : 'w-72';

  return (
    <>
    {/* Keeps the page column where it was while the overlay floats above it. */}
    {overlay && <div aria-hidden="true" className="w-12 shrink-0" />}
    {overlay && <div aria-hidden="true" data-testid="sidebar-backdrop" className="fixed inset-0 z-30 bg-background/60" onClick={onToggle} />}
    <aside id="controls-sidebar" aria-label="Simulation controls" className={`${width} transition-all duration-300 motion-reduce:transition-none border-r border-border bg-sidebar flex flex-col shrink-0`}>
      <div className={`flex items-center ${collapsed ? 'justify-center' : 'justify-between px-4'} py-3 border-b border-border`}>
        {!collapsed && <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Controls</span>}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand controls sidebar' : 'Collapse controls sidebar'}
          aria-expanded={!collapsed}
          aria-controls="controls-sidebar"
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {collapsed ? <ChevronRight aria-hidden="true" className="h-4 w-4" /> : <ChevronLeft aria-hidden="true" className="h-4 w-4" />}
        </button>
      </div>

      <div className={`flex-1 overflow-y-auto ${collapsed ? 'px-2' : 'px-4'} py-4 space-y-4`}>
        <SliderControl icon={Cpu} label="Server Utilisation" value={config.serverUtil} min={10} max={100} step={1} unit="%" onChange={v => set({ serverUtil: v })} collapsed={collapsed} locked={locked} />
        <SliderControl icon={Thermometer} label="Outside Temperature" value={config.outsideTemp} min={-5} max={40} step={0.5} unit="°C" onChange={v => set({ outsideTemp: v })} collapsed={collapsed} locked={locked} />
        <SliderControl icon={Droplets} label="Water Stress Index" value={config.waterStress} min={0} max={1} step={0.05} unit="" onChange={v => set({ waterStress: +v.toFixed(2) })} collapsed={collapsed} locked={locked} />
        <SliderControl icon={Gauge} label="Chilled Water Setpoint" value={config.chilledWaterSetpoint} min={5} max={15} step={0.5} unit="°C" onChange={v => set({ chilledWaterSetpoint: v })} collapsed={collapsed} locked={locked} />

        {!collapsed && locked && (
          <p id="controls-locked-note" data-testid="controls-locked-note" className="rounded border border-border px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
            {OPERATOR_REQUIRED_TEXT}. These controls are locked because TwinGrid is read-only for viewers. You can still see every value and the live data.
          </p>
        )}

        {!collapsed && (
          <>
            <Separator className="bg-border/50" />
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Cooling Mode</Label>
              <Select value={config.coolingMode} disabled={locked} onValueChange={(v) => set({ coolingMode: v as CoolingMode })}>
                <SelectTrigger aria-label="Cooling mode" aria-describedby={locked ? 'controls-locked-note' : undefined} className="bg-muted border-border text-foreground text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['Auto', 'Evaporative', 'Closed-Loop', 'Free Air', 'Hybrid'].map(m => (
                    <SelectItem key={m} value={m}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Separator className="bg-border/50" />

            <Button onClick={onRunSim} disabled={simRunning || locked} aria-disabled={simRunning || locked} aria-describedby={locked ? 'controls-locked-note' : undefined} className="w-full gap-2">
              {simRunning ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Play className="h-4 w-4" />}
              {simRunning ? 'Simulating…' : 'Run 24h Simulation'}
            </Button>
          </>
        )}

        <FeatureNav orientation="vertical" collapsed={collapsed} />
      </div>
    </aside>
    </>
  );
}
