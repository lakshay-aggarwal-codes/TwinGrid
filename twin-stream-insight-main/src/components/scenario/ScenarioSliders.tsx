import { useEffect, useId, useRef } from 'react';
import { FlaskConical } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import type { CoolingMode, SimConfig } from '@/hooks/useSimulation';
import { describeInputs, physicsVersionOf, type InputsEcho } from '@/hooks/useWhatIf';
import type { WhatIfResponse } from '@/api/apiClient';

export type ScenarioControl = 'serverUtil' | 'outsideTemp' | 'waterStress' | 'chilledWaterSetpoint' | 'coolingMode';

const COOLING_MODES: CoolingMode[] = ['Auto', 'Evaporative', 'Closed-Loop', 'Free Air', 'Hybrid'];

interface SlidersProps {
  config: SimConfig;
  onChange: (c: SimConfig) => void;
  /** Unique per instance, so labels and notes bind to the right control. */
  idPrefix?: string;
  /** A control the current view's request does not use shows this note instead of implying an effect. */
  notes?: Partial<Record<ScenarioControl, string>>;
}

/**
 * Radix puts the slider role on the thumb, and the vendored shadcn `Slider` offers no way to name it. The name and
 * value text are set on the thumb here so every slider has an accessible name (and a value with its unit).
 */
function LabelledSlider({
  label,
  valueText,
  describedBy,
  ...rest
}: { label: string; valueText: string; describedBy?: string } & React.ComponentProps<typeof Slider>) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const thumb = ref.current?.querySelector('[role="slider"]');
    if (!thumb) return;
    thumb.setAttribute('aria-label', label);
    thumb.setAttribute('aria-valuetext', valueText);
    if (describedBy) thumb.setAttribute('aria-describedby', describedBy);
    else thumb.removeAttribute('aria-describedby');
  });
  return (
    <div ref={ref}>
      <Slider {...rest} />
    </div>
  );
}

/** The one set of scenario controls, shared by the Simulation Lab, the What-If tab and the Analytics sidebar. */
export function ScenarioSliders({ config, onChange, idPrefix, notes = {} }: SlidersProps) {
  const auto = useId();
  const id = idPrefix ?? auto;
  const set = (p: Partial<SimConfig>) => onChange({ ...config, ...p });
  const note = (key: ScenarioControl) =>
    notes[key] ? (
      <p id={`${id}-${key}-note`} className="text-[10px] text-muted-foreground italic">
        {notes[key]}
      </p>
    ) : null;
  const noteId = (key: ScenarioControl) => (notes[key] ? `${id}-${key}-note` : undefined);

  const sliders: Array<{ key: Exclude<ScenarioControl, 'coolingMode'>; label: string; value: number; unit: string; min: number; max: number; step: number; apply: (v: number) => Partial<SimConfig> }> = [
    { key: 'serverUtil', label: 'Server utilisation', value: config.serverUtil, unit: '%', min: 10, max: 100, step: 1, apply: (v) => ({ serverUtil: v }) },
    { key: 'outsideTemp', label: 'Outside temperature', value: config.outsideTemp, unit: '°C', min: -5, max: 40, step: 0.5, apply: (v) => ({ outsideTemp: v }) },
    { key: 'waterStress', label: 'Water stress index', value: config.waterStress, unit: '', min: 0, max: 1, step: 0.05, apply: (v) => ({ waterStress: +v.toFixed(2) }) },
    { key: 'chilledWaterSetpoint', label: 'Chilled water setpoint', value: config.chilledWaterSetpoint, unit: '°C', min: 5, max: 15, step: 0.5, apply: (v) => ({ chilledWaterSetpoint: v }) },
  ];

  return (
    <div className="space-y-3">
      {sliders.map((s) => (
        <div key={s.key} className="space-y-1">
          <div className="flex items-center justify-between">
            <Label id={`${id}-${s.key}-label`} className="text-xs text-muted-foreground">
              {s.label}
            </Label>
            <span className="font-mono text-xs text-foreground">
              {s.value}
              {s.unit}
            </span>
          </div>
          <LabelledSlider
            label={s.label}
            valueText={`${s.value}${s.unit}`}
            describedBy={noteId(s.key)}
            min={s.min}
            max={s.max}
            step={s.step}
            value={[s.value]}
            onValueChange={([v]) => set(s.apply(v))}
          />
          {note(s.key)}
        </div>
      ))}
      <div className="space-y-1">
        <Label htmlFor={`${id}-mode`} className="text-xs text-muted-foreground">
          Cooling mode
        </Label>
        <Select value={config.coolingMode} onValueChange={(v) => set({ coolingMode: v as CoolingMode })}>
          <SelectTrigger id={`${id}-mode`} aria-describedby={noteId('coolingMode')} className="bg-muted border-border text-sm h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COOLING_MODES.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {note('coolingMode')}
      </div>
    </div>
  );
}

/** The label every what-if result carries, with the inputs it was produced from and the physics version if sent. */
export function PreviewNotice({ data, inputs }: { data: WhatIfResponse; inputs: InputsEcho }) {
  const physics = physicsVersionOf(data);
  return (
    <div className="space-y-0.5 text-[11px] text-muted-foreground" data-testid="preview-notice">
      <p className="flex items-center gap-1.5 font-medium text-foreground">
        <FlaskConical aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
        Preview — simulated, constant inputs
      </p>
      <p>Inputs: {describeInputs(inputs)}.</p>
      {physics && <p>Physics version: {physics}</p>}
    </div>
  );
}
