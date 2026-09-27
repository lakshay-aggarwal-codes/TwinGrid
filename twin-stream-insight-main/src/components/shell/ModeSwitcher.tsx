import { MODE_LABELS, type VisualizationMode } from "@/three/visualizationModes";

const MODES: VisualizationMode[] = ["physical", "thermal", "energy", "cooling", "sustainability"];

interface ModeSwitcherProps {
  mode: VisualizationMode;
  onChange: (mode: VisualizationMode) => void;
}

/**
 * Small persistent-chrome control, not a nav bar -- a row of text buttons
 * that toggle which facility-wide metric is tinting the racks. Stays this
 * minimal deliberately (see the brief's "minimal persistent chrome"
 * principle); a floating pill was equally valid, this just reuses the
 * header's existing row layout instead of adding a new floating element.
 */
export function ModeSwitcher({ mode, onChange }: ModeSwitcherProps) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5" role="radiogroup" aria-label="Visualization mode">
      {MODES.map((m) => (
        <button
          key={m}
          role="radio"
          aria-checked={mode === m}
          onClick={() => onChange(m)}
          className={`px-2 py-1 rounded text-[11px] uppercase tracking-wide transition-colors ${
            mode === m
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {MODE_LABELS[m]}
        </button>
      ))}
    </div>
  );
}
