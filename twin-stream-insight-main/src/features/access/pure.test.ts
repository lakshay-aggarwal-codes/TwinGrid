import { describe, expect, it, vi } from 'vitest';
import { validateRequest, NAME_MAX, PURPOSE_MAX } from './validate';
import { passwordStrength } from './strength';
import { takeActivationToken, forgetActivationToken } from './activationToken';
import { clearTicket, loadTicket, saveTicket, TICKET_KEY } from './ticket';
import * as fx from '@/contract/fixtures-access';
import { AccessRequestCreated, AccessRequestStatus, ActivateOk, DemoSessionResponse, ResendAck } from './schemas';

describe('validateRequest', () => {
  it('accepts a name and email with no purpose', () => {
    expect(validateRequest({ name: 'Ada', email: 'ada@example.com', purpose: '' })).toEqual({});
  });
  it('requires name and email, and rejects a malformed email', () => {
    expect(validateRequest({ name: ' ', email: '', purpose: '' })).toEqual({ name: 'Enter your name.', email: 'Enter your email address.' });
    expect(validateRequest({ name: 'Ada', email: 'ada@', purpose: '' }).email).toMatch(/name@example\.com/);
  });
  it('enforces the length limits', () => {
    expect(validateRequest({ name: 'a'.repeat(NAME_MAX + 1), email: 'a@b.co', purpose: '' }).name).toMatch(/at most/);
    expect(validateRequest({ name: 'a', email: 'a@b.co', purpose: 'x'.repeat(PURPOSE_MAX + 1) }).purpose).toMatch(/at most/);
  });
});

describe('passwordStrength', () => {
  it('is "Too short" below 12 characters and says how many there are', () => {
    const s = passwordStrength('short');
    expect(s.label).toBe('Too short');
    expect(s.level).toBe(0);
    expect(s.hint).toMatch(/12/);
    expect(s.hint).toMatch(/5 so far/);
  });
  it('rates longer, more varied passwords higher', () => {
    expect(passwordStrength('aaaaaaaaaaaa').label).toBe('Fair');
    expect(passwordStrength('Aaaaaaaaaaa1').label).toBe('Good');
    expect(passwordStrength('Abcdefghijkl1!xyz').label).toBe('Strong');
  });
});

describe('ticket storage', () => {
  it('round-trips and clears', () => {
    sessionStorage.clear();
    expect(loadTicket()).toBeNull();
    saveTicket({ ref: 'AR-1', token: 't' });
    expect(loadTicket()).toEqual({ ref: 'AR-1', token: 't' });
    clearTicket();
    expect(loadTicket()).toBeNull();
  });
  it('treats corrupt storage as no ticket', () => {
    sessionStorage.setItem(TICKET_KEY, '{not json');
    expect(loadTicket()).toBeNull();
    sessionStorage.setItem(TICKET_KEY, JSON.stringify({ ref: 1, token: 2 }));
    expect(loadTicket()).toBeNull();
  });
  it('survives storage that throws (never throws itself)', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => saveTicket({ ref: 'AR-1', token: 't' })).not.toThrow();
    expect(loadTicket()).toBeNull();
    get.mockRestore();
    set.mockRestore();
  });
});

describe('takeActivationToken', () => {
  it('reads the token from the hash and removes the hash from the URL at once', () => {
    forgetActivationToken();
    window.history.replaceState(null, '', '/activate#token=abc.def_123');
    expect(takeActivationToken()).toBe('abc.def_123');
    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/activate');
    forgetActivationToken();
  });
  it('returns null when there is no token', () => {
    forgetActivationToken();
    window.history.replaceState(null, '', '/activate');
    expect(takeActivationToken()).toBeNull();
  });
});

describe('§8 fixtures match the runtime schemas', () => {
  it('parses every documented body', () => {
    expect(AccessRequestCreated.safeParse(fx.accessRequestCreated).success).toBe(true);
    for (const s of [fx.statusPending, fx.statusApproved, fx.statusActivated, fx.statusRejected, fx.statusExpired]) {
      expect(AccessRequestStatus.safeParse(s).success).toBe(true);
    }
    expect(ResendAck.safeParse(fx.resendAck).success).toBe(true);
    expect(ActivateOk.safeParse(fx.activateOk).success).toBe(true);
    expect(DemoSessionResponse.safeParse(fx.demoSession).success).toBe(true);
  });
  it('rejects a status this client does not know instead of guessing', () => {
    expect(AccessRequestStatus.safeParse({ ...fx.statusPending, status: 'banana' }).success).toBe(false);
    expect(AccessRequestCreated.safeParse({ ...fx.accessRequestCreated, status: 'approved' }).success).toBe(false);
  });
  it('the demo session has no refresh token', () => {
    expect(Object.keys(fx.demoSession)).not.toContain('refresh_token');
  });
});
