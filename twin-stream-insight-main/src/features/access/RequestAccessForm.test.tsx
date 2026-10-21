import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as fx from '@/contract/fixtures-access';

const submitAccessRequest = vi.fn();
vi.mock('./api', async (orig) => ({ ...(await orig<typeof import('./api')>()), submitAccessRequest: (...a: unknown[]) => submitAccessRequest(...a) }));

import { RequestAccessForm } from './RequestAccessForm';

function fill(name: string, email: string, purpose = '') {
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: name } });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } });
  if (purpose) fireEvent.change(screen.getByLabelText(/Purpose/), { target: { value: purpose } });
}
const form = () => screen.getByRole('button', { name: /send request|sending/i }).closest('form')!;

describe('RequestAccessForm', () => {
  const onSubmitted = vi.fn();
  const onBack = vi.fn();
  beforeEach(() => {
    submitAccessRequest.mockReset();
    onSubmitted.mockReset();
    onBack.mockReset();
  });
  const setup = () => render(<RequestAccessForm onSubmitted={onSubmitted} onBack={onBack} />);

  it('has labelled name, email and optional purpose fields and starts without errors', () => {
    setup();
    expect(screen.getByRole('heading', { name: 'Request viewer access' })).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveAttribute('autocomplete', 'name');
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText(/Purpose \(optional\)/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('never claims an email was sent or that an account exists', () => {
    setup();
    expect(document.body).not.toHaveTextContent(/(email|link) (was|has been) sent|we('ve| have) sent|your account/i);
  });

  it('shows an accessible error summary, focuses it, and marks the fields invalid', async () => {
    setup();
    fireEvent.submit(form());
    const summary = await screen.findByTestId('error-summary');
    expect(summary).toHaveAttribute('role', 'alert');
    expect(summary).toHaveTextContent('Enter your name.');
    expect(summary).toHaveTextContent('Enter your email address.');
    await waitFor(() => expect(summary).toHaveFocus());
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-describedby', expect.stringContaining('access-name-error'));
    expect(submitAccessRequest).not.toHaveBeenCalled();
  });

  it('a summary link moves focus to its field', async () => {
    setup();
    fireEvent.submit(form());
    fireEvent.click(await screen.findByRole('link', { name: 'Enter your email address.' }));
    expect(screen.getByLabelText('Email')).toHaveFocus();
  });

  it('validates a field inline once it has been left', () => {
    setup();
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'nope' } });
    expect(screen.queryByText(/name@example\.com/)).toBeNull();
    fireEvent.blur(screen.getByLabelText('Email'));
    expect(screen.getByText(/name@example\.com/)).toBeInTheDocument();
  });

  it('submits the details and hands the created request to the caller', async () => {
    submitAccessRequest.mockResolvedValue({ kind: 'ok', data: fx.accessRequestCreated });
    setup();
    fill('Ada', 'ada@example.com', 'Look around');
    fireEvent.submit(form());
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith(expect.objectContaining({ ref: 'AR-7K3Q9X' })));
    expect(submitAccessRequest).toHaveBeenCalledWith({ name: 'Ada', email: 'ada@example.com', purpose: 'Look around' });
  });

  it('disables the button, announces progress, and ignores a second submit while sending', async () => {
    let finish!: (v: unknown) => void;
    submitAccessRequest.mockReturnValue(new Promise((r) => (finish = r)));
    setup();
    fill('Ada', 'ada@example.com');
    fireEvent.submit(form());
    fireEvent.submit(form());
    expect(submitAccessRequest).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled();
    expect(screen.getByText('Sending your request…')).toBeInTheDocument();
    finish({ kind: 'ok', data: fx.accessRequestCreated });
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
  });

  it.each([
    ['rate_limited', /too many requests/i],
    ['offline', /could not reach/i],
    ['invalid', /could not accept/i],
    ['unexpected', /something went wrong/i],
  ])('shows a %s failure as an alert and re-enables the form', async (kind, text) => {
    submitAccessRequest.mockResolvedValue({ kind });
    setup();
    fill('Ada', 'ada@example.com');
    fireEvent.submit(form());
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
    expect(screen.getByRole('button', { name: 'Send request' })).toBeEnabled();
    expect(onSubmitted).not.toHaveBeenCalled();
  });

  it('Back to sign in calls onBack', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'Back to sign in' }));
    expect(onBack).toHaveBeenCalled();
  });
});
