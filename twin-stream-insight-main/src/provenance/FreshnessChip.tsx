import { cn } from '@/lib/utils';
import { FRESH_STYLE } from './icons';
import { Pill } from './parts';
import type { ProvenanceView } from './model';

interface FreshnessChipProps {
  view: ProvenanceView;
  /**
   * Render ONE visually hidden live region that announces the freshness STATE (not the age), so assistive tech hears
   * transitions rather than every tick. `disconnected` is assertive (matches the FE-03 vocabulary). Mount it once per screen.
   */
  announce?: boolean;
  className?: string;
}

/** Freshness chip. Renders nothing when the data has no freshness (REST payloads): absence is not "live". */
export function FreshnessChip({ view, announce = false, className }: FreshnessChipProps) {
  const chip = view.freshness;
  if (!chip) return null;
  return (
    <>
      <Pill
        icon={chip.icon}
        className={cn(FRESH_STYLE[chip.state], className)}
        spin={chip.state === 'connecting'}
        data={{ 'data-freshness': chip.state }}
      >
        {chip.text}
      </Pill>
      {announce && (
        <span className="sr-only" role="status" aria-live={chip.assertive ? 'assertive' : 'polite'} data-freshness-announcement={chip.state}>
          {chip.announcement}
        </span>
      )}
    </>
  );
}
