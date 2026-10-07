import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { ProvenanceBadge } from './ProvenanceBadge';
import { ProvenanceDetail } from './ProvenanceDetail';
import type { ProvenanceView } from './model';

interface ProvenanceStripProps {
  view: ProvenanceView;
  announce?: boolean;
  /** Optional: show the Preview inputs here (e.g. the configuration being previewed). */
  children?: ReactNode;
  className?: string;
}

/** Tier 2 -- panel/page header: source/context line, scenario and run id when present, all flags, and the detail popover. */
export function ProvenanceStrip({ view, announce, children, className }: ProvenanceStripProps) {
  const full = view.flags.filter((f) => !f.inBadge);
  return (
    <div data-provenance-strip className={cn('flex flex-col gap-1 text-xs text-muted-foreground', className)}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ProvenanceBadge view={view} announce={announce} />
        <span data-provenance-line>{view.strip.line}</span>
        {view.strip.scenario && <span data-provenance-scenario>Scenario {view.strip.scenario}</span>}
        {view.strip.run && <span data-provenance-run>Run {view.strip.run}</span>}
        <ProvenanceDetail view={view} />
      </div>
      {full.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-0.5">
          {full.map((f, i) => (
            <li key={`${f.id}-${i}`} data-flag={f.id}>
              {f.text}
            </li>
          ))}
        </ul>
      )}
      {view.flags.some((f) => f.id === 'preview') && <span data-provenance-preview>{view.flags.find((f) => f.id === 'preview')?.text}</span>}
      {children}
    </div>
  );
}
