import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { ICONS } from './icons';
import type { ProvenanceIconKey } from './model';

interface PillProps {
  icon: ProvenanceIconKey;
  className: string;
  title?: string | null;
  children: ReactNode;
  data?: Record<`data-${string}`, string>;
  spin?: boolean;
}

/** Icon (decorative) + text. `shrink-0` + no truncation: layout can never hide an origin or flag. */
export function Pill({ icon, className, title, children, data, spin }: PillProps) {
  const Icon = ICONS[icon];
  return (
    <span
      title={title ?? undefined}
      className={cn('inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[11px] font-medium leading-none', className)}
      {...data}
    >
      <Icon aria-hidden="true" data-prov-icon={icon} className={cn('h-3 w-3 shrink-0', spin && 'animate-spin motion-reduce:animate-none')} />
      <span>{children}</span>
    </span>
  );
}
