import { ciLevelText, type PairedDifferenceView } from '@/evaluation/model';

/**
 * The only confidence intervals the backend provides: paired PPO-minus-baseline differences. Shown exactly as sent;
 * an interval that includes zero is shown, not hidden; a missing interval says "uncertainty not provided".
 */
export function PairedDifferences({ items, ciLevel }: { items: readonly PairedDifferenceView[]; ciLevel: number | undefined }) {
  if (items.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="no-paired-differences">
        Paired-difference confidence intervals: not provided (no PPO candidate in this report).
      </p>
    );
  }
  return (
    <section aria-label="Paired differences" className="space-y-1">
      <h3 className="text-xs font-medium text-foreground">Paired difference (PPO minus baseline), t-based, {ciLevelText(ciLevel)}</h3>
      <ul className="space-y-0.5 text-xs text-foreground">
        {items.map((d) => (
          <li key={`${d.baseline}-${d.scope}`} data-paired={`${d.baseline}:${d.scope}`}>
            vs {d.baseline}, across {d.scope}: <span className="font-mono">{d.text}</span>
            {d.n !== null && <span className="text-muted-foreground"> · n={d.n}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
