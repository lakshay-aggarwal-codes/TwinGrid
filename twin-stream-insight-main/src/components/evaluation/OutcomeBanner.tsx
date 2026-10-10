import { ArrowRightLeft, BadgeCheck, CircleHelp, CircleSlash, FlaskConical, type LucideIcon } from 'lucide-react';
import type { OutcomeKind, OutcomeView } from '@/evaluation/model';

/** One icon shape per outcome kind (text is the primary cue; colour is not used to rank outcomes). */
const ICONS: Record<OutcomeKind, LucideIcon> = {
  A: BadgeCheck,
  B: FlaskConical,
  C: ArrowRightLeft,
  NOT_EVALUATED: CircleSlash,
  unrecognised: CircleHelp,
};

/**
 * The outcome banner. Every outcome (positive, negative, inconclusive, not evaluated, unknown) renders through this one
 * component with identical layout, border and weight: a negative or empty result is never smaller, tabbed away or
 * toned down relative to a positive one. All sentences come from the backend, verbatim.
 */
export function OutcomeBanner({ outcome }: { outcome: OutcomeView }) {
  const Icon = ICONS[outcome.kind];
  return (
    <section
      aria-label="Evaluation outcome"
      data-outcome={outcome.kind}
      data-outcome-code={outcome.code}
      className="space-y-1.5 rounded-md border-2 border-border bg-muted/40 p-3"
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Icon aria-hidden="true" data-outcome-icon={outcome.kind} className="h-4 w-4 shrink-0" />
        <span data-testid="outcome-headline">{outcome.headline}</span>
      </h2>
      <p className="text-xs text-foreground" data-testid="outcome-claim">
        Claim allowed: <span className="font-medium">{outcome.claimAllowed}</span>
      </p>
      <p className="text-xs text-muted-foreground" data-testid="outcome-definition" data-definition-provided={outcome.definitionProvided}>
        {outcome.definitionProvided ? outcome.definition : `${outcome.code} — ${outcome.definition}`}
      </p>
      {outcome.reason !== null && (
        <p className="text-xs text-muted-foreground" data-testid="outcome-reason">
          Reason: {outcome.reason}
        </p>
      )}
    </section>
  );
}
