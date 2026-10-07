import { Info } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import type { ProvenanceView } from './model';

interface ProvenanceDetailProps {
  view: ProvenanceView;
  /** Render the rows inline (a section) instead of behind the popover trigger. */
  inline?: boolean;
  className?: string;
}

function Rows({ view }: { view: ProvenanceView }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs" data-provenance-detail>
      {view.detail.map((r) => (
        <div key={r.id} className="contents" data-detail-row={r.id} data-reported={r.reported ? 'true' : 'false'}>
          <dt className="text-muted-foreground">{r.label}</dt>
          <dd className={cn('break-words', !r.reported && 'italic text-muted-foreground')}>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Tier 3 -- every provenance field, with an explicit "not reported" row for each missing one.
 * Keyboard: the trigger is a real button; Radix returns focus on close and closes on Escape.
 */
export function ProvenanceDetail({ view, inline = false, className }: ProvenanceDetailProps) {
  if (inline) {
    return (
      <section aria-label="Provenance details" className={className}>
        <Rows view={view} />
      </section>
    );
  }
  return (
    <Popover>
      <PopoverTrigger
        type="button"
        aria-label="Provenance details"
        className={cn(
          'inline-flex items-center gap-1 rounded-sm px-1 text-[11px] underline underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          className,
        )}
      >
        <Info aria-hidden="true" className="h-3 w-3" />
        <span>Details</span>
      </PopoverTrigger>
      <PopoverContent className="w-80 max-h-[70vh] overflow-y-auto" aria-label="Provenance details">
        <Rows view={view} />
      </PopoverContent>
    </Popover>
  );
}
