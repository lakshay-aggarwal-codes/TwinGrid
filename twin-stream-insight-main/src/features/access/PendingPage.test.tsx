import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fx from '@/contract/fixtures-access';

const fetchRequestStatus = vi.fn();
const resendActivation = vi.fn();
vi.mock('./api', async (orig) => ({
  ...(await orig<typeof import('./api')>()),
  fetchRequestStatus: (...a: unknown[]) => fetchRequestStatus(...a),
  resendActivation: (...a: unknown[]) => resendActivation(...a),
}));

import { PendingPage } from './PendingPage';
import { TICKET_KEY } from './ticket';

const TOKEN = 'secret-status-token-xyz';
const ok = (data: unknown) => ({ kind: 'ok', data });
let hidden = false;

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function setHidden(value: boolean) {
  hidden = value;
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  hidden = false;
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  fetchRequestStatus.mockReset();
  resendActivation.mockReset();
  sessionStorage.clear();
  sessionStorage.setItem(TICKET_KEY, JSON.stringify({ ref: 'AR-7K3Q9X', token: TOKEN }));
  window.history.replaceState(null, '', '/access/pending');
});
afterEach(() => vi.useRealTimers());

describe('PendingPage', () => {
  it('shows the reference, status and next action for a pending request, and never the token', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    expect(screen.getByTestId('request-ref')).toHaveTextContent('AR-7K3Q9X');
    expect(screen.getByTestId('request-status')).toHaveTextContent('Awaiting decision');
    expect(screen.getByTestId('next-action')).toHaveTextContent("Your request reached TwinGrid and is awaiting the owner's decision.");
    expect(document.body.textContent).not.toContain(TOKEN);
    expect(fetchRequestStatus).toHaveBeenCalledWith('AR-7K3Q9X', TOKEN);
  });

  it('exposes the next action as a polite live region', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    const live = screen.getByTestId('next-action');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveAttribute('role', 'status');
  });

  it.each([
    ['approved', fx.statusApproved, /check your email/i],
    ['rejected', fx.statusRejected, /did not approve/i],
    ['expired', fx.statusExpired, /expired/i],
    ['activated', fx.statusActivated, /sign in/i],
  ])('renders the %s state', async (_name, body, text) => {
    fetchRequestStatus.mockResolvedValue(ok(body));
    render(<PendingPage />);
    await flush();
    expect(screen.getByTestId('next-action')).toHaveTextContent(text);
    expect(document.body).not.toHaveTextContent(/(email|link) (was|has been) sent/i);
  });

  it('approved offers a resend, and shows the neutral server wording', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusApproved));
    resendActivation.mockResolvedValue({ kind: 'ok' });
    render(<PendingPage />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Resend activation link' }));
    await flush();
    expect(resendActivation).toHaveBeenCalledWith('AR-7K3Q9X', TOKEN);
    expect(screen.getByTestId('resend-note')).toHaveTextContent('If your request is approved, a new link has been sent.');
  });

  it('activated offers "Go to sign in", which clears the ticket and goes to /', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusActivated));
    render(<PendingPage />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Go to sign in' }));
    expect(sessionStorage.getItem(TICKET_KEY)).toBeNull();
    expect(window.location.pathname).toBe('/');
  });

  it('a 404 says it could not find the request, and submitting again clears the ticket', async () => {
    fetchRequestStatus.mockResolvedValue({ kind: 'not_found' });
    render(<PendingPage />);
    await flush();
    expect(screen.getByText("We couldn't find this request. Submit again.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Submit a new request' }));
    expect(sessionStorage.getItem(TICKET_KEY)).toBeNull();
    expect(window.location.pathname).toBe('/');
  });

  it('recovers after a reload from the ticket in sessionStorage', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    const first = render(<PendingPage />);
    await flush();
    first.unmount();
    fetchRequestStatus.mockClear();
    render(<PendingPage />);
    await flush();
    expect(fetchRequestStatus).toHaveBeenCalledWith('AR-7K3Q9X', TOKEN);
    expect(screen.getByTestId('request-ref')).toHaveTextContent('AR-7K3Q9X');
  });

  it('without a ticket it makes no request and says so', async () => {
    sessionStorage.clear();
    render(<PendingPage />);
    await flush(60_000);
    expect(fetchRequestStatus).not.toHaveBeenCalled();
    expect(screen.getByText(/no access request in progress/i)).toBeInTheDocument();
  });

  it('polls every 5 s at first, then backs off to a 30 s ceiling while the status is unchanged', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    expect(fetchRequestStatus).toHaveBeenCalledTimes(1);
    await flush(4_999);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(2); // t=5s
    await flush(10_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(3); // t=15s
    await flush(20_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(4); // t=35s
    await flush(29_999);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(4);
    await flush(1);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(5); // t=65s: capped at 30 s
    await flush(30_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(6);
  });

  it('returns to 5 s when the status changes', async () => {
    fetchRequestStatus.mockResolvedValueOnce(ok(fx.statusPending)).mockResolvedValueOnce(ok(fx.statusPending)).mockResolvedValue(ok(fx.statusApproved));
    render(<PendingPage />);
    await flush(); // call 1
    await flush(5_000); // call 2 (same) -> next delay 10 s
    await flush(10_000); // call 3 (changed) -> next delay 5 s
    expect(screen.getByTestId('request-status')).toHaveTextContent('Approved');
    await flush(5_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(4);
  });

  it('stops polling once the request reaches a final status', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusRejected));
    render(<PendingPage />);
    await flush(120_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(1);
  });

  it('pauses while the tab is hidden and checks again, at once, when it is shown', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    setHidden(true);
    await flush(120_000);
    expect(fetchRequestStatus).toHaveBeenCalledTimes(1);
    setHidden(false);
    await flush();
    expect(fetchRequestStatus).toHaveBeenCalledTimes(2);
  });

  it('shows a visible offline notice, keeps the last status, retries, and clears the notice on success', async () => {
    fetchRequestStatus.mockResolvedValueOnce(ok(fx.statusPending)).mockResolvedValueOnce({ kind: 'offline' }).mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    expect(screen.queryByTestId('offline-notice')).toBeNull();
    await flush(5_000);
    expect(screen.getByTestId('offline-notice')).toHaveTextContent(/can't reach twingrid/i);
    expect(screen.getByTestId('request-status')).toHaveTextContent('Awaiting decision'); // last known status stays visible
    await flush(10_000);
    expect(screen.queryByTestId('offline-notice')).toBeNull();
  });

  it('"Check now" retries immediately', async () => {
    fetchRequestStatus.mockResolvedValueOnce({ kind: 'offline' }).mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    expect(screen.getByTestId('offline-notice')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await flush();
    expect(fetchRequestStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId('offline-notice')).toBeNull();
  });

  it('the browser going offline shows the notice without waiting for a poll', async () => {
    fetchRequestStatus.mockResolvedValue(ok(fx.statusPending));
    render(<PendingPage />);
    await flush();
    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(screen.getByTestId('offline-notice')).toBeInTheDocument();
  });
});
