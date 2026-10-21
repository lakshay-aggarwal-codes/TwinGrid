import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { usePageTitle } from '@/hooks/usePageTitle';
import { AccessShell } from './AccessShell';
import { resendActivation, type AccessStatus } from './api';
import { clearTicket, loadTicket, navigateTo, type AccessTicket } from './ticket';
import { useRequestStatus } from './useRequestStatus';

/** Exact copy kept in one place. None of it claims an email was sent or that an account exists before activation. */
const STATUS_COPY: Record<AccessStatus, { label: string; next: string }> = {
  pending: {
    label: 'Awaiting decision',
    next: "Your request reached TwinGrid and is awaiting the owner's decision. You can leave this page open; it checks for updates on its own.",
  },
  approved: {
    label: 'Approved',
    next: 'Your request was approved. Check your email for an activation link, then open it to set your password. If you cannot find it, resend the link.',
  },
  activated: {
    label: 'Activated',
    next: 'Your access is activated. Sign in to continue.',
  },
  rejected: {
    label: 'Not approved',
    next: 'The owner did not approve this request, so there is nothing to activate.',
  },
  expired: {
    label: 'Expired',
    next: 'This request expired before it was completed. Submit a new request if you still want access.',
  },
};

function toSignIn(clear: boolean) {
  if (clear) clearTicket();
  navigateTo('/');
}

/** /access/pending: the visitor's request status. Public route (rendered outside the sign-in gate). */
export function PendingPage() {
  usePageTitle('Request status – TwinGrid');
  const [ticket] = useState<AccessTicket | null>(() => loadTicket());
  const { phase, data, offline, checkNow } = useRequestStatus(ticket);
  const [resendNote, setResendNote] = useState<string | null>(null);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    document.getElementById('pending-heading')?.focus();
  }, []);

  async function onResend() {
    if (!ticket || resending) return;
    setResending(true);
    setResendNote(null);
    const result = await resendActivation(ticket.ref, ticket.token);
    setResending(false);
    if (result.kind === 'ok') setResendNote('If your request is approved, a new link has been sent.');
    else if (result.kind === 'rate_limited') setResendNote('Too many attempts. Wait a minute and try again.');
    else if (result.kind === 'not_found') setResendNote("We couldn't find this request. Submit again.");
    else if (result.kind === 'offline') setResendNote('Could not reach TwinGrid. Check your connection and try again.');
    else setResendNote('Something went wrong. Please try again in a moment.');
  }

  const heading = (
    <h1 id="pending-heading" tabIndex={-1} className="text-xl font-semibold outline-none">
      Your access request
    </h1>
  );

  if (!ticket) {
    return (
      <AccessShell labelledBy="pending-heading">
        {heading}
        <p className="text-sm text-muted-foreground">
          There is no access request in progress in this browser tab. A request is only remembered for the life of the tab it was made in.
        </p>
        <Button type="button" className="w-full sm:w-auto" onClick={() => toSignIn(false)}>
          Back to sign in
        </Button>
      </AccessShell>
    );
  }

  if (phase === 'not_found') {
    return (
      <AccessShell labelledBy="pending-heading">
        {heading}
        <p role="status" className="text-sm text-foreground">
          We couldn&apos;t find this request. Submit again.
        </p>
        <Button type="button" className="w-full sm:w-auto" onClick={() => toSignIn(true)}>
          Submit a new request
        </Button>
      </AccessShell>
    );
  }

  const status = data?.status ?? null;
  const copy = status ? STATUS_COPY[status] : null;

  return (
    <AccessShell labelledBy="pending-heading">
      {heading}
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Reference</dt>
        <dd>
          <code data-testid="request-ref" className="break-all">
            {ticket.ref}
          </code>
        </dd>
        <dt className="text-muted-foreground">Status</dt>
        <dd data-testid="request-status">{copy ? copy.label : 'Checking…'}</dd>
      </dl>

      {/* Live region: a status change is announced without moving focus. */}
      <div role="status" aria-live="polite" data-testid="next-action" className="text-sm text-foreground">
        {copy ? copy.next : 'Checking the status of your request…'}
      </div>

      {offline && (
        <div data-testid="offline-notice" role="status" className="rounded-md border border-warning/50 bg-warning/10 p-2 text-sm text-foreground">
          <p>
            Can&apos;t reach TwinGrid right now.{' '}
            {status ? 'The status above is the last one we saw. ' : ''}We keep trying automatically.
          </p>
          <Button type="button" variant="outline" size="sm" className="mt-2" onClick={checkNow}>
            Check now
          </Button>
        </div>
      )}

      {status === 'approved' && (
        <div className="space-y-2">
          <Button type="button" variant="outline" className="w-full sm:w-auto" onClick={() => void onResend()} disabled={resending}>
            {resending ? 'Resending…' : 'Resend activation link'}
          </Button>
          <p role="status" aria-live="polite" data-testid="resend-note" className="min-h-[1.25rem] text-sm text-muted-foreground">
            {resendNote ?? ''}
          </p>
        </div>
      )}

      {status === 'activated' && (
        <Button type="button" className="w-full sm:w-auto" onClick={() => toSignIn(true)}>
          Go to sign in
        </Button>
      )}
      {(status === 'rejected' || status === 'expired') && (
        <Button type="button" className="w-full sm:w-auto" onClick={() => toSignIn(true)}>
          {status === 'expired' ? 'Submit a new request' : 'Back to sign in'}
        </Button>
      )}
      {(status === 'pending' || status === 'approved') && (
        <Button type="button" variant="ghost" className="w-full sm:w-auto" onClick={() => toSignIn(false)}>
          Back to sign in
        </Button>
      )}
      {phase === 'loading' && !offline && <p className="sr-only">Loading</p>}
    </AccessShell>
  );
}
