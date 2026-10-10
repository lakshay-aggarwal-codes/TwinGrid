import type { ReactNode } from 'react';

/** The existing raw sliders keep working under this honest name until a backend registry covers every use of them. */
export function CustomParameters({ children }: { children: ReactNode }) {
  return (
    <section aria-label="Custom parameters (preview)" className="space-y-2" data-testid="custom-parameters">
      <h3 className="text-sm font-semibold text-foreground">Custom parameters (preview)</h3>
      <p className="text-[11px] text-muted-foreground">A parameter set with no scenario identity. Results are previews, not scenario results.</p>
      {children}
    </section>
  );
}
