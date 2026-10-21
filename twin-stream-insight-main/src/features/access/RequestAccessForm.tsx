import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { submitAccessRequest, type AccessRequestCreated } from './api';
import { FormErrorSummary, type SummaryError } from './FormErrorSummary';
import { PURPOSE_MAX, validateRequest, type RequestErrors, type RequestFields } from './validate';

const FIELD_IDS = { name: 'access-name', email: 'access-email', purpose: 'access-purpose' } as const;
const FIELD_ORDER = ['name', 'email', 'purpose'] as const;

const SERVER_MESSAGES = {
  invalid: 'TwinGrid could not accept those details. Check your name and email address and try again.',
  rate_limited: 'Too many requests. Wait a minute and try again.',
  offline: 'Could not reach TwinGrid. Check your connection and try again.',
  unexpected: 'Something went wrong on our side. Please try again in a moment.',
} as const;

/**
 * "Request viewer access": name, email, optional purpose. This only ASKS the owner; nothing here implies that an
 * account exists. On success the caller gets the created request so it can keep {ref, token} and show the pending page.
 */
export function RequestAccessForm({
  onSubmitted,
  onBack,
}: {
  onSubmitted: (created: AccessRequestCreated) => void;
  onBack: () => void;
}) {
  const [fields, setFields] = useState<RequestFields>({ name: '', email: '', purpose: '' });
  const [touched, setTouched] = useState<Partial<Record<keyof RequestFields, boolean>>>({});
  const [summary, setSummary] = useState<SummaryError[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false); // synchronous guard: state updates are async, a second submit can land before they apply
  const summaryRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const errors: RequestErrors = validateRequest(fields);
  const shown = (k: keyof RequestFields) => (touched[k] ? errors[k] : undefined);

  function set(k: keyof RequestFields, value: string) {
    setFields((f) => ({ ...f, [k]: value }));
  }
  const blur = (k: keyof RequestFields) => setTouched((t) => ({ ...t, [k]: true }));

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current) return;
    setServerError(null);
    const found = validateRequest(fields);
    const list: SummaryError[] = FIELD_ORDER.filter((k) => found[k]).map((k) => ({ fieldId: FIELD_IDS[k], message: found[k] as string }));
    if (list.length > 0) {
      setTouched({ name: true, email: true, purpose: true });
      setSummary(list);
      // Wait for the summary to render, then move focus to it.
      setTimeout(() => summaryRef.current?.focus(), 0);
      return;
    }
    setSummary([]);
    submittingRef.current = true;
    setSubmitting(true);
    const result = await submitAccessRequest(fields);
    if (result.kind === 'ok') {
      onSubmitted(result.data);
      return; // the caller leaves this screen; keep the button disabled meanwhile
    }
    setServerError(SERVER_MESSAGES[result.kind]);
    submittingRef.current = false;
    setSubmitting(false);
  }

  const describedBy = (k: keyof RequestFields, hint?: string) =>
    [shown(k) ? `${FIELD_IDS[k]}-error` : null, hint ?? null].filter(Boolean).join(' ') || undefined;

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-labelledby="access-heading"
      className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-4 sm:p-6"
    >
      <div className="space-y-1">
        <h1 id="access-heading" ref={headingRef} tabIndex={-1} className="text-xl font-semibold outline-none">
          Request viewer access
        </h1>
        <p className="text-sm text-muted-foreground">
          Ask the owner for read-only access. Nothing is set up until the owner approves your request and you finish activation.
        </p>
      </div>

      <FormErrorSummary errors={summary} summaryRef={summaryRef} />

      <div className="space-y-2">
        <Label htmlFor={FIELD_IDS.name}>Name</Label>
        <Input
          id={FIELD_IDS.name}
          name="name"
          autoComplete="name"
          required
          aria-invalid={shown('name') ? true : undefined}
          aria-describedby={describedBy('name')}
          value={fields.name}
          onChange={(e) => set('name', e.target.value)}
          onBlur={() => blur('name')}
        />
        {shown('name') && (
          <p id={`${FIELD_IDS.name}-error`} className="text-sm text-destructive-text">
            {shown('name')}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor={FIELD_IDS.email}>Email</Label>
        <Input
          id={FIELD_IDS.email}
          name="email"
          type="email"
          autoComplete="email"
          required
          aria-invalid={shown('email') ? true : undefined}
          aria-describedby={describedBy('email')}
          value={fields.email}
          onChange={(e) => set('email', e.target.value)}
          onBlur={() => blur('email')}
        />
        {shown('email') && (
          <p id={`${FIELD_IDS.email}-error`} className="text-sm text-destructive-text">
            {shown('email')}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor={FIELD_IDS.purpose}>Purpose (optional)</Label>
        <Textarea
          id={FIELD_IDS.purpose}
          name="purpose"
          rows={3}
          aria-invalid={shown('purpose') ? true : undefined}
          aria-describedby={describedBy('purpose', 'access-purpose-hint')}
          value={fields.purpose}
          onChange={(e) => set('purpose', e.target.value)}
          onBlur={() => blur('purpose')}
        />
        <p id="access-purpose-hint" className="text-xs text-muted-foreground">
          What would you like to look at? Up to {PURPOSE_MAX} characters.
        </p>
        {shown('purpose') && (
          <p id={`${FIELD_IDS.purpose}-error`} className="text-sm text-destructive-text">
            {shown('purpose')}
          </p>
        )}
      </div>

      {serverError && (
        <p id="access-server-error" role="alert" className="text-sm text-destructive-text">
          {serverError}
        </p>
      )}

      {/* Polite live region: announces the in-flight state to screen readers. */}
      <p role="status" aria-live="polite" className="min-h-[1.25rem] text-sm text-muted-foreground">
        {submitting ? 'Sending your request…' : ''}
      </p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Button type="submit" className="w-full sm:w-auto" disabled={submitting}>
          {submitting ? 'Sending…' : 'Send request'}
        </Button>
        <Button type="button" variant="ghost" className="w-full sm:w-auto" onClick={onBack} disabled={submitting}>
          Back to sign in
        </Button>
      </div>
    </form>
  );
}
