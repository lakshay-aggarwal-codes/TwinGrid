import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as fx from '@/contract/fixtures-access';

const startDemo = vi.fn();
const submitAccessRequest = vi.fn();
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ status: 'signed-out', username: null, role: null, notice: null, demo: false, login: vi.fn(), logout: vi.fn(), startDemo }),
}));
vi.mock('@/features/access/api', async (orig) => ({
  ...(await orig<typeof import('@/features/access/api')>()),
  submitAccessRequest: (...a: unknown[]) => submitAccessRequest(...a),
}));

import { LoginScreen } from './LoginScreen.tsx';
import { DemoError } from '@/authClient';
import { TICKET_KEY } from '@/features/access/ticket';

beforeEach(() => {
  startDemo.mockReset();
  submitAccessRequest.mockReset();
  sessionStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('LoginScreen visitor options', () => {
  it('keeps the sign-in form and adds the two visitor entries, with no account-creation wording', () => {
    render(<LoginScreen />);
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Request viewer access' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Explore read-only demo' })).toBeInTheDocument();
    expect(screen.queryByText(/register|create account|sign up/i)).toBeNull();
  });

  it('starts the demo through the auth client', async () => {
    startDemo.mockResolvedValue(undefined);
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore read-only demo' }));
    await waitFor(() => expect(startDemo).toHaveBeenCalledTimes(1));
  });

  it('shows "Demo is not enabled on this server." on a 404', async () => {
    startDemo.mockRejectedValue(new DemoError('Demo is not enabled on this server.', 404));
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore read-only demo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Demo is not enabled on this server.');
    expect(screen.getByRole('button', { name: 'Explore read-only demo' })).toBeEnabled();
  });

  it('shows a generic message for an unexpected demo error (never the raw exception)', async () => {
    startDemo.mockRejectedValue(new Error('TypeError: secret internals'));
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore read-only demo' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not be started/i);
    expect(alert).not.toHaveTextContent('secret internals');
  });

  it('ignores a second click while the demo is starting', () => {
    startDemo.mockReturnValue(new Promise(() => undefined));
    render(<LoginScreen />);
    const button = screen.getByRole('button', { name: 'Explore read-only demo' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(startDemo).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /starting demo/i })).toBeDisabled();
  });

  it('opens the request form and goes back to sign-in', () => {
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Request viewer access' }));
    expect(screen.getByRole('heading', { name: 'Request viewer access' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to sign in' }));
    expect(screen.getByRole('heading', { name: /sign in to twingrid/i })).toBeInTheDocument();
  });

  it('a sent request stores {ref, token} for this tab and moves to /access/pending', async () => {
    submitAccessRequest.mockResolvedValue({ kind: 'ok', data: fx.accessRequestCreated });
    render(<LoginScreen />);
    fireEvent.click(screen.getByRole('button', { name: 'Request viewer access' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada' } });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@example.com' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Send request' }).closest('form')!);
    await waitFor(() => expect(window.location.pathname).toBe('/access/pending'));
    expect(JSON.parse(sessionStorage.getItem(TICKET_KEY) as string)).toEqual({ ref: 'AR-7K3Q9X', token: 'status-token-placeholder' });
  });
});
