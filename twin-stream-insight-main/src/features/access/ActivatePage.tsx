import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { usePageTitle } from '@/hooks/usePageTitle';
import { AccessShell } from './AccessShell';
import { activateAccount, PASSWORD_MAX, PASSWORD_MIN } from './api';
import { forgetActivationToken, takeActivationToken } from './activationToken';
import { FormErrorSummary, type SummaryError } from './FormErrorSummary';
import { passwordStrength } from './strength';
import { loadTicket, navigateTo } from './ticket';

const MESSAGES = {
  invalid_or_expired: 'This activation link is invalid, has expired, or has already been used.',
  invalid: `That password was not accepted. Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`,
  rate_limited: 'Too many attempts. Wait a minute and try again.',
  offline: 'Could not reach TwinGrid. Check your connection and try again.',
  unexpected: 'Something went wrong on our side. Please try again in a moment.',
} as const;

function passwordProblem(password: string): string | null {
  if (password.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`;
  if (password.length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters.`;
  return null;
}

/** The backend issues secrets.token_urlsafe(32): always 43 URL-safe characters. Anything else can never be valid, so it gets the dead-link page, not a form. */
const TOKEN_FORMAT = /^[A-Za-z0-9_-]{43}$/;

/** /activate#token=...: set a password for an approved request. Public route. Creates no session: the visitor signs in afterwards. */
export function ActivatePage() {
  usePageTitle('Activate access – TwinGrid');
  // Read once, strip the fragment from the address bar right away. useState's initializer keeps the value across re-renders.
  const [token] = useState<string | null>(() => takeActivationToken());
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [reveal, setReveal] = useState(false);
  const [summary, setSummary] = useState<SummaryError[]>([]);
  const [failure, setFailure] = useState<keyof typeof MESSAGES | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const submittingRef = useRef(false);
  const summaryRef = useRef<HTMLDivElement>(null);
  const strength = passwordStrength(password, PASSWORD_MIN);
  const hasRequest = loadTicket() !== null;

  useEffect(() => {
    document.getElementById('activate-heading')?.focus();
  }, [done]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current || !token) return;
    setFailure(null);
    const problems: SummaryError[] = [];
    const pw = passwordProblem(password);
    if (pw) problems.push({ fieldId: 'activate-password', message: pw });
    if (confirm !== password) problems.push({ fieldId: 'activate-confirm', message: 'The two passwords do not match.' });
    if (problems.length > 0) {
      setSummary(problems);
      setTimeout(() => summaryRef.current?.focus(), 0);
      return;
    }
    setSummary([]);
    submittingRef.current = true;
    setSubmitting(true);
    const result = await activateAccount(token, password);
    submittingRef.current = false;
    setSubmitting(false);
    if (result.kind === 'ok') {
      forgetActivationToken();
      setPassword('');
      setConfirm('');
      setDone(true);
      return;
    }
    if (result.kind === 'invalid_or_expired') forgetActivationToken();
    setFailure(result.kind);
    setPassword('');
    setConfirm('');
  }

  if (done) {
    return (
      <AccessShell labelledBy="activate-heading">
        <h1 id="activate-heading" tabIndex={-1} className="text-xl font-semibold outline-none">
          Access activated
        </h1>
        <p role="status" className="text-sm text-foreground">
          Your password is set. You can sign in now.
        </p>
        <Button type="button" className="w-full sm:w-auto" onClick={() => navigateTo('/')}>
          Go to sign in
        </Button>
      </AccessShell>
    );
  }

  const linkDead = !token || !TOKEN_FORMAT.test(token) || failure === 'invalid_or_expired';
  if (linkDead) {
    return (
      <AccessShell labelledBy="activate-heading">
        <h1 id="activate-heading" tabIndex={-1} className="text-xl font-semibold outline-none">
          Activation link problem
        </h1>
        <p role="alert" className="text-sm text-destructive-text">
          {token === null && failure === null
            ? 'This activation link is incomplete. Open the link from your email again.'
            : MESSAGES.invalid_or_expired}
        </p>
        <p className="text-sm text-muted-foreground">
          {hasRequest ? 'Check your request status to resend a new link.' : 'If you still need access, request it again from the sign-in page.'}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          {hasRequest && (
            <Button type="button" className="w-full sm:w-auto" onClick={() => navigateTo('/access/pending')}>
              Check request status
            </Button>
          )}
          <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={() => navigateTo('/')}>
            Back to sign in
          </Button>
        </div>
      </AccessShell>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== password;
  const inputType = reveal ? 'text' : 'password';

  return (
    <AccessShell labelledBy="activate-heading">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <div className="space-y-1">
          <h1 id="activate-heading" tabIndex={-1} className="text-xl font-semibold outline-none">
            Set your password
          </h1>
          <p className="text-sm text-muted-foreground">
            Choose a password of {PASSWORD_MIN} to {PASSWORD_MAX} characters to finish activating your access.
          </p>
        </div>

        <FormErrorSummary errors={summary} summaryRef={summaryRef} />

        <div className="space-y-2">
          <Label htmlFor="activate-password">New password</Label>
          <div className="flex gap-2">
            <Input
              id="activate-password"
              name="new-password"
              type={inputType}
              autoComplete="new-password"
              required
              className="min-w-0"
              aria-describedby="activate-strength"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button
              type="button"
              variant="outline"
              aria-pressed={reveal}
              aria-controls="activate-password activate-confirm"
              onClick={() => setReveal((r) => !r)}
            >
              {reveal ? 'Hide' : 'Show'}
              <span className="sr-only"> passwords</span>
            </Button>
          </div>
          <p id="activate-strength" aria-live="polite" data-testid="strength" className="text-xs text-muted-foreground">
            {password ? `Strength: ${strength.label}. ${strength.hint}` : `At least ${PASSWORD_MIN} characters.`}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="activate-confirm">Confirm password</Label>
          <Input
            id="activate-confirm"
            name="confirm-password"
            type={inputType}
            autoComplete="new-password"
            required
            aria-invalid={mismatch ? true : undefined}
            aria-describedby={mismatch ? 'activate-confirm-error' : undefined}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && (
            <p id="activate-confirm-error" className="text-sm text-destructive-text">
              The two passwords do not match.
            </p>
          )}
        </div>

        {failure && (
          <p role="alert" className="text-sm text-destructive-text">
            {MESSAGES[failure]}
          </p>
        )}

        <p role="status" aria-live="polite" className="min-h-[1.25rem] text-sm text-muted-foreground">
          {submitting ? 'Activating…' : ''}
        </p>

        <Button type="submit" className="w-full sm:w-auto" disabled={submitting}>
          {submitting ? 'Activating…' : 'Activate access'}
        </Button>
      </form>
    </AccessShell>
  );
}
