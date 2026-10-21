import type { ReactNode } from 'react';

interface Props {
  /** The backend's identifier for the rule that raised the alert (the alert `type`). */
  readonly ruleId: string;
  /** The value the rule was applied to, as the backend stored it. */
  readonly value: number | null;
  readonly valueLabel: string;
  /** The rule's threshold, when the backend reported it; otherwise null. */
  readonly threshold: number | null;
  /** ISO text of when the value was observed, already formatted for display, or null. */
  readonly observedAt: string | null;
  readonly origin: string | null | undefined;
  /** Where to look at the evidence (a link supplied by the page, so this component needs no router). */
  readonly evidence?: ReactNode;
}

function Row({ label, children, testId }: { label: string; children: ReactNode; testId: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd data-testid={testId} className="text-right break-words">
        {children}
      </dd>
    </div>
  );
}

const NOT_REPORTED = 'not reported';

/** Task 16: the rule behind an alert, with only what the backend recorded. Nothing is derived or guessed here. */
export function AlertRuleFacts({ ruleId, value, valueLabel, threshold, observedAt, origin, evidence }: Props) {
  return (
    <section aria-label="Rule that raised this alert" data-testid="alert-rule-facts" className="space-y-1">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Rule</h4>
      <dl className="space-y-0.5 text-[11px] font-mono">
        <Row label="Rule" testId="rule-id">
          {ruleId}
        </Row>
        <Row label={valueLabel} testId="rule-value">
          {value === null ? NOT_REPORTED : value.toFixed(4)}
        </Row>
        <Row label="Threshold" testId="rule-threshold">
          {threshold === null ? NOT_REPORTED : threshold.toFixed(4)}
        </Row>
        <Row label="Observed at" testId="rule-observed-at">
          {observedAt ?? NOT_REPORTED}
        </Row>
        <Row label="Origin" testId="rule-origin">
          {origin ? origin : `${NOT_REPORTED} (Unverified source)`}
        </Row>
        <Row label="Evidence" testId="rule-evidence">
          {evidence ?? 'the fields in this panel are all that is stored with this alert'}
        </Row>
      </dl>
    </section>
  );
}
