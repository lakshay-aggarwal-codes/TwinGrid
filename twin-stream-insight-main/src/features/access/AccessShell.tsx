import type { ReactNode } from 'react';

/** Centered card used by the public access pages. Fits a 320 px viewport: min-w-0 + break-words, no fixed widths. */
export function AccessShell({ children, labelledBy }: { children: ReactNode; labelledBy: string }) {
  return (
    <main className="min-h-screen flex items-start justify-center bg-background p-4 sm:items-center">
      <section
        aria-labelledby={labelledBy}
        className="w-full min-w-0 max-w-md space-y-4 break-words rounded-lg border border-border bg-card p-4 sm:p-6"
      >
        {children}
      </section>
    </main>
  );
}
