import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fx from '@/contract/fixtures-access';

function jwt(claims: Record<string, unknown>): string {
  const payload = btoa(JSON.stringify(claims)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `h.${payload}.s`;
}
const demoJwt = (secondsLeft: number, demo = true) => jwt({ sub: 'demo', role: 'viewer', demo, exp: Math.floor(Date.now() / 1000) + secondsLeft });
const demoBody = (access = demoJwt(1800)) => ({ ...fx.demoSession, access_token: access });
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = (status: number, body: unknown = {}) => ({ ok: false, status, json: async () => body });
const STORAGE_KEY = 'twingrid.session';

async function load(fetchMock: ReturnType<typeof vi.fn>) {
  vi.resetModules();
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/');
  vi.stubGlobal('fetch', fetchMock);
  return import('./authClient');
}

describe('startDemoSession', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('POSTs /auth/demo-session with no credentials and signs in as a read-only demo viewer', async () => {
    const f = vi.fn().mockResolvedValue(ok(demoBody()));
    const a = await load(f);
    await a.startDemoSession();
    const [url, init] = f.mock.calls[0];
    expect(url).toBe('https://api.example.com/auth/demo-session');
    expect(init.method).toBe('POST');
    expect(init.body).not.toMatch(/password|username/);
    expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-in', role: 'viewer', demo: true, notice: null });
    expect(await a.getToken()).toBe(demoBody().access_token);
  });

  it('decodes the demo claim from the access token', async () => {
    const f = vi.fn().mockResolvedValue(ok({ ...demoBody(demoJwt(1800, true)), demo: false }));
    const a = await load(f);
    await a.startDemoSession();
    expect(a.getAuthSnapshot().demo).toBe(true);
  });

  it('a normal sign-in is not a demo', async () => {
    const f = vi.fn().mockResolvedValue(ok({ access_token: jwt({ exp: Math.floor(Date.now() / 1000) + 900 }), refresh_token: 'r', token_type: 'bearer', role: 'viewer' }));
    const a = await load(f);
    await a.login('alice', 'pw');
    expect(a.getAuthSnapshot().demo).toBe(false);
  });

  it('never writes anything to sessionStorage (there is no refresh token to keep)', async () => {
    const f = vi.fn().mockResolvedValue(ok(demoBody()));
    const a = await load(f);
    await a.startDemoSession();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  it.each([
    [404, 'Demo is not enabled on this server.'],
    [503, /temporarily unavailable/],
    [429, /too many/i],
    [500, /could not be started \(500\)/],
  ])('HTTP %s is a DemoError with a user-safe message and leaves the visitor signed out', async (status, message) => {
    const f = vi.fn().mockResolvedValue(fail(status as number, status === 404 ? fx.notFound : fx.demoUnavailable));
    const a = await load(f);
    await expect(a.startDemoSession()).rejects.toMatchObject({ name: 'DemoError', status, message: typeof message === 'string' ? message : expect.stringMatching(message) });
    expect(a.getAuthSnapshot().status).toBe('signed-out');
  });

  it('a network failure and an unexpected body are DemoErrors', async () => {
    const a1 = await load(vi.fn().mockRejectedValue(new TypeError('network')));
    await expect(a1.startDemoSession()).rejects.toMatchObject({ name: 'DemoError', message: expect.stringMatching(/could not reach/i) });
    const a2 = await load(vi.fn().mockResolvedValue(ok({ access_token: 'x' })));
    await expect(a2.startDemoSession()).rejects.toMatchObject({ name: 'DemoError', message: expect.stringMatching(/not understood/i) });
    expect(a2.getAuthSnapshot().status).toBe('signed-out');
  });

  it('ends at the token expiry with the demo notice and cannot be renewed', async () => {
    vi.useFakeTimers();
    const f = vi.fn().mockResolvedValue(ok(demoBody(demoJwt(1800))));
    const a = await load(f);
    await a.startDemoSession();
    await vi.advanceTimersByTimeAsync(1_799_000);
    expect(a.getAuthSnapshot().status).toBe('signed-in');
    await vi.advanceTimersByTimeAsync(2_000);
    expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-out', demo: false, notice: a.DEMO_ENDED_NOTICE });
    await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
    expect(f).toHaveBeenCalledTimes(1); // never tried to refresh
  });

  it('is usable right up to expiry (no early-refresh margin, since it cannot refresh)', async () => {
    const token = demoJwt(30);
    const f = vi.fn().mockResolvedValue(ok(demoBody(token)));
    const a = await load(f);
    await a.startDemoSession();
    expect(await a.getToken()).toBe(token);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('forceRefresh (after a 401) ends the demo with the notice instead of refreshing', async () => {
    const f = vi.fn().mockResolvedValue(ok(demoBody()));
    const a = await load(f);
    await a.startDemoSession();
    await expect(a.forceRefresh()).rejects.toBeInstanceOf(a.AuthRequiredError);
    expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-out', notice: a.DEMO_ENDED_NOTICE });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('logout from the demo is immediate and makes no server call', async () => {
    const f = vi.fn().mockResolvedValue(ok(demoBody()));
    const a = await load(f);
    await a.startDemoSession();
    await a.logout();
    expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-out', demo: false });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('a response that arrives after sign-out cannot resurrect a session', async () => {
    let resolve!: (v: unknown) => void;
    const f = vi.fn().mockReturnValue(new Promise((r) => (resolve = r)));
    const a = await load(f);
    const pending = a.startDemoSession();
    await a.logout();
    resolve(ok(demoBody()));
    await pending;
    expect(a.getAuthSnapshot().status).toBe('signed-out');
  });
});
