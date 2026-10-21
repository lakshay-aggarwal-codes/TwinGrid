import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const activateAccount = vi.fn();
vi.mock('./api', async (orig) => ({ ...(await orig<typeof import('./api')>()), activateAccount: (...a: unknown[]) => activateAccount(...a) }));

import { ActivatePage } from './ActivatePage';
import { forgetActivationToken } from './activationToken';
import { TICKET_KEY } from './ticket';

const PW = 'correct horse battery';
const fields = () => [screen.getByLabelText('New password'), screen.getByLabelText('Confirm password')] as const;
function fillBoth(a: string, b = a) {
  const [p, c] = fields();
  fireEvent.change(p, { target: { value: a } });
  fireEvent.change(c, { target: { value: b } });
}
const form = () => screen.getByRole('button', { name: /activate/i }).closest('form')!;

beforeEach(() => {
  activateAccount.mockReset();
  forgetActivationToken();
  sessionStorage.clear();
  window.history.replaceState(null, '', '/activate#token=abc123');
});

describe('ActivatePage', () => {
  it('removes the token from the address bar immediately', () => {
    render(<ActivatePage />);
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain('abc123');
  });

  it('still has the token under StrictMode double rendering', async () => {
    activateAccount.mockResolvedValue({ kind: 'ok' });
    render(
      <StrictMode>
        <ActivatePage />
      </StrictMode>,
    );
    fillBoth(PW);
    fireEvent.submit(form());
    await waitFor(() => expect(activateAccount).toHaveBeenCalledWith('abc123', PW));
  });

  it('activates, then offers sign-in and sends the visitor to /', async () => {
    activateAccount.mockResolvedValue({ kind: 'ok' });
    render(<ActivatePage />);
    fillBoth(PW);
    fireEvent.submit(form());
    expect(await screen.findByRole('heading', { name: 'Access activated' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Go to sign in' }));
    expect(window.location.pathname).toBe('/');
  });

  it.each([
    ['too short', 'short', 'short', 'Use at least 12 characters.'],
    ['mismatch', PW, PW + 'x', 'The two passwords do not match.'],
  ])('%s: shows a focused error summary and does not call the server', async (_n, a, b, message) => {
    render(<ActivatePage />);
    fillBoth(a, b);
    fireEvent.submit(form());
    const summary = await screen.findByTestId('error-summary');
    expect(summary).toHaveTextContent(message);
    await waitFor(() => expect(summary).toHaveFocus());
    expect(activateAccount).not.toHaveBeenCalled();
  });

  it('flags a mismatch inline as the visitor types', () => {
    render(<ActivatePage />);
    fillBoth(PW, 'different');
    expect(screen.getByText('The two passwords do not match.')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows a strength hint in a polite live region', () => {
    render(<ActivatePage />);
    const hint = screen.getByTestId('strength');
    expect(hint).toHaveAttribute('aria-live', 'polite');
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'short' } });
    expect(hint).toHaveTextContent(/Too short/);
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'Abcdefghijkl1!xyz' } });
    expect(hint).toHaveTextContent(/Strong/);
  });

  it('has a keyboard-accessible reveal toggle (a real button with aria-pressed)', () => {
    render(<ActivatePage />);
    const toggle = screen.getByRole('button', { name: /show passwords/i });
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByLabelText('New password')).toHaveAttribute('type', 'password');
    fireEvent.click(toggle);
    expect(screen.getByRole('button', { name: /hide passwords/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('New password')).toHaveAttribute('type', 'text');
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('type', 'text');
  });

  it('ignores a second submit while activating', async () => {
    let finish!: (v: unknown) => void;
    activateAccount.mockReturnValue(new Promise((r) => (finish = r)));
    render(<ActivatePage />);
    fillBoth(PW);
    fireEvent.submit(form());
    fireEvent.submit(form());
    expect(activateAccount).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /activating/i })).toBeDisabled();
    finish({ kind: 'ok' });
    await screen.findByRole('heading', { name: 'Access activated' });
  });

  it('an invalid, expired or used link shows one clear message and no form', async () => {
    activateAccount.mockResolvedValue({ kind: 'invalid_or_expired' });
    render(<ActivatePage />);
    fillBoth(PW);
    fireEvent.submit(form());
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid, has expired, or has already been used/i);
    expect(screen.queryByLabelText('New password')).toBeNull();
  });

  it('points to the request status when this tab has a request', async () => {
    sessionStorage.setItem(TICKET_KEY, JSON.stringify({ ref: 'AR-1', token: 't' }));
    activateAccount.mockResolvedValue({ kind: 'invalid_or_expired' });
    render(<ActivatePage />);
    fillBoth(PW);
    fireEvent.submit(form());
    fireEvent.click(await screen.findByRole('button', { name: 'Check request status' }));
    expect(window.location.pathname).toBe('/access/pending');
  });

  it.each([
    ['rate_limited', /too many attempts/i],
    ['offline', /could not reach/i],
    ['invalid', /not accepted/i],
    ['unexpected', /something went wrong/i],
  ])('a %s failure keeps the form, clears the passwords and shows an alert', async (kind, text) => {
    activateAccount.mockResolvedValue({ kind });
    render(<ActivatePage />);
    fillBoth(PW);
    fireEvent.submit(form());
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(screen.getByLabelText('New password')).toHaveValue('');
  });

  it('a link without a token says it is incomplete', () => {
    forgetActivationToken();
    window.history.replaceState(null, '', '/activate');
    render(<ActivatePage />);
    expect(screen.getByRole('alert')).toHaveTextContent(/incomplete/i);
    expect(screen.queryByLabelText('New password')).toBeNull();
  });
});
