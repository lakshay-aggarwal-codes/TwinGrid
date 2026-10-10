import type { ChartModel } from '@/telemetry/history/model';
import { qualityClass } from '@/telemetry/history/model';

const Swatch = ({ children }: { children: React.ReactNode }) => (
  <svg width="28" height="12" aria-hidden="true" className="shrink-0 text-foreground">
    {children}
  </svg>
);

/** Legend: every mark on the chart has a shape cue and text, so colour is never the only signal. */
export function HistoryLegend({ model }: { model: ChartModel }) {
  const invalid = model.excluded.filter((p) => qualityClass(p.quality) === 'invalid').length;
  const unrecognised = model.excluded.length - invalid;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Chart legend" data-testid="history-legend">
      <li className="flex items-center gap-1.5" data-legend="line">
        <Swatch>
          <line x1="0" y1="6" x2="28" y2="6" stroke="hsl(var(--primary))" strokeWidth="2" />
          <circle cx="14" cy="6" r="3" fill="hsl(var(--primary))" />
        </Swatch>
        Valid sample (quality ok)
      </li>
      {model.gapBands.length > 0 && (
        <li className="flex items-center gap-1.5" data-legend="gap">
          <Swatch>
            <rect x="1" y="1" width="26" height="10" fill="none" stroke="currentColor" strokeDasharray="2 2" />
            <line x1="4" y1="11" x2="12" y2="1" stroke="currentColor" />
            <line x1="12" y1="11" x2="20" y2="1" stroke="currentColor" />
          </Swatch>
          Gap reported by the backend: no valid samples, line broken ({model.gapBands.length})
        </li>
      )}
      {invalid > 0 && (
        <li className="flex items-center gap-1.5" data-legend="invalid">
          <Swatch>
            <line x1="14" y1="0" x2="14" y2="12" stroke="currentColor" strokeWidth="1.5" strokeDasharray="5 3" />
          </Swatch>
          Invalid sample: not plotted, listed in the table ({invalid})
        </li>
      )}
      {unrecognised > 0 && (
        <li className="flex items-center gap-1.5" data-legend="unrecognised">
          <Swatch>
            <line x1="14" y1="0" x2="14" y2="12" stroke="currentColor" strokeWidth="1.5" strokeDasharray="1 3" />
          </Swatch>
          Unrecognised quality: not plotted, listed in the table ({unrecognised})
        </li>
      )}
    </ul>
  );
}
