import { cn } from '@/lib/utils';
import { FreshnessChip } from './FreshnessChip';
import { ORIGIN_BORDER, TONE } from './icons';
import { Pill } from './parts';
import type { ProvenanceView } from './model';

interface ProvenanceBadgeProps {
  view: ProvenanceView;
  /** Forward to FreshnessChip: mount a single announcing instance per screen. */
  announce?: boolean;
  className?: string;
}

/**
 * Tier 1 -- compact, beside every value block / KPI / chart / result card.
 * Always shows the origin (Simulated / Measured / Replayed / Unverified source); it is not optional and not collapsible,
 * so the simulated state cannot be hidden by layout. Flags that change how a number must be read are included.
 */
export function ProvenanceBadge({ view, announce, className }: ProvenanceBadgeProps) {
  return (
    <span role="group" aria-label="Data provenance" data-provenance-badge={view.origin.state} className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      <Pill icon={view.origin.icon} className={ORIGIN_BORDER[view.origin.state]} title={view.origin.tooltip} data={{ 'data-origin': view.origin.state }}>
        {view.origin.text}
      </Pill>
      {view.flags
        .filter((f) => f.inBadge)
        .map((f, i) => (
          <Pill key={`${f.id}-${i}`} icon={f.icon} className={TONE[f.tone]} title={f.text} data={{ 'data-flag': f.id }}>
            {f.shortText}
          </Pill>
        ))}
      <FreshnessChip view={view} announce={announce} />
    </span>
  );
}
