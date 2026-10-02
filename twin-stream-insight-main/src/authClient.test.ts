import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function fakeJwt(expSecondsFromNow: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `h.${payload}.s`;
}

type Mock = ReturnType<typeof vi.fn>;
const STORAGE_KEY = 'twingrid.session';

function tokens(access = fakeJwt(900), refresh = 'refresh-1', role = 'viewer') {
  return { access_token: access, refresh_token: refresh, role };
}
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = (status: number) => ({ ok: false, status, statusText: 'x', json: async () => ({}) });

async function load(fetchMock: Mock, env: Record<string, string | boolean> = {}) {
  vi.resetModules();
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/');
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v as string);
  vi.stubGlobal('fetch', fetchMock);
  return import('./authClient');
}

describe('authClient', () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  describe('login', () => {
    it('posts credentials to the shared base URL and signs in', async () => {
      const f = vi.fn().mockResolvedValue(ok(tokens(fakeJwt(900), 'r1', 'operator')));
      const a = await load(f);
      await a.login('  alice ', 'pw');
      expect(f.mock.calls[0][0]).toBe('https://api.example.com/auth/login');
      expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ username: 'alice', password: 'pw' });
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-in', username: 'alice', role: 'operator' });
      await expect(a.getToken()).resolves.toMatch(/^h\./);
      expect(f).toHaveBeenCalledTimes(1);
    });

    it('keeps the access token out of storage; only the refresh token is stored', async () => {
      const access = fakeJwt(900);
      const a = await load(vi.fn().mockResolvedValue(ok(tokens(access, 'r-secret'))));
      await a.login('alice', 'pw');
      const stored = JSON.stringify({ ...sessionStorage, ...localStorage });
      expect(stored).toContain('r-secret');
      expect(stored).not.toContain(access);
      expect(Object.keys(localStorage)).toHaveLength(0);
    });

    it.each([
      [401, /Invalid username or password/],
      [429, /Too many sign-in attempts/],
      [503, /Sign-in failed \(503\)/],
    ])('maps HTTP %i to a user-safe LoginError and stays signed out', async (status, message) => {
      const a = await load(vi.fn().mockResolvedValue(fail(status)));
      await expect(a.login('alice', 'bad')).rejects.toThrow(message);
      await expect(a.login('alice', 'bad')).rejects.toBeInstanceOf(a.LoginError);
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('reports an unreachable server', async () => {
      const a = await load(vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
      await expect(a.login('alice', 'pw')).rejects.toThrow(/Could not reach the server/);
    });
  });

  describe('getToken / refresh', () => {
    it('requires sign-in and makes no request when there is no session', async () => {
      const f = vi.fn();
      const a = await load(f);
      await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
      expect(f).not.toHaveBeenCalled();
    });

    it('returns the cached token while it has more than a minute left', async () => {
      const f = vi.fn().mockResolvedValue(ok(tokens(fakeJwt(900))));
      const a = await load(f);
      await a.login('alice', 'pw');
      await Promise.all([a.getToken(), a.getToken()]);
      expect(f).toHaveBeenCalledTimes(1);
    });

    it('refreshes with the refresh token when the access token is close to expiry, and rotates it', async () => {
      const f = vi
        .fn()
        .mockResolvedValueOnce(ok(tokens(fakeJwt(30), 'r1')))
        .mockResolvedValueOnce(ok(tokens(fakeJwt(900), 'r2')));
      const a = await load(f);
      await a.login('alice', 'pw');
      await a.getToken();
      expect(f.mock.calls[1][0]).toBe('https://api.example.com/auth/refresh');
      expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ refresh_token: 'r1' });
      expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)!).refreshToken).toBe('r2');
      expect(a.getAuthSnapshot().username).toBe('alice');
    });

    it('shares ONE refresh request between concurrent callers (refresh tokens are single-use)', async () => {
      const f = vi
        .fn()
        .mockResolvedValueOnce(ok(tokens(fakeJwt(5), 'r1')))
        .mockResolvedValueOnce(ok(tokens(fakeJwt(900), 'r2')));
      const a = await load(f);
      await a.login('alice', 'pw');
      await Promise.all([a.getToken(), a.getToken(), a.getToken(), a.forceRefresh()]);
      expect(f).toHaveBeenCalledTimes(2); // 1 login + 1 refresh
    });

    it('signs out when the refresh token is rejected', async () => {
      const f = vi.fn().mockResolvedValueOnce(ok(tokens(fakeJwt(5), 'r1'))).mockResolvedValueOnce(fail(401));
      const a = await load(f);
      await a.login('alice', 'pw');
      await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-out', username: null });
      expect(a.getAuthSnapshot().notice).toMatch(/session has ended/i);
      expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('keeps the session and can retry after a transient refresh failure (inFlight is reset)', async () => {
      const f = vi
        .fn()
        .mockResolvedValueOnce(ok(tokens(fakeJwt(5), 'r1')))
        .mockResolvedValueOnce(fail(503))
        .mockResolvedValueOnce(ok(tokens(fakeJwt(900), 'r2')));
      const a = await load(f);
      await a.login('alice', 'pw');
      await expect(a.getToken()).rejects.toThrow(/Token refresh failed: 503/);
      expect(a.getAuthSnapshot().status).toBe('signed-in');
      await expect(a.getToken()).resolves.toMatch(/^h\./);
    });
  });

  describe('logout', () => {
    it('signs out immediately, revokes the refresh token server-side and clears storage', async () => {
      const f = vi.fn().mockResolvedValueOnce(ok(tokens(fakeJwt(900), 'r1'))).mockResolvedValueOnce({ ok: true, status: 204 });
      const a = await load(f);
      await a.login('alice', 'pw');
      const done = a.logout();
      expect(a.getAuthSnapshot().status).toBe('signed-out'); // before the network call resolves
      await done;
      expect(f.mock.calls[1][0]).toBe('https://api.example.com/auth/logout');
      expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ refresh_token: 'r1' });
      expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
      await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
    });

    it('still signs out when the server cannot be reached', async () => {
      const f = vi.fn().mockResolvedValueOnce(ok(tokens())).mockRejectedValueOnce(new TypeError('offline'));
      const a = await load(f);
      await a.login('alice', 'pw');
      await expect(a.logout()).resolves.toBeUndefined();
      expect(a.getAuthSnapshot().status).toBe('signed-out');
    });

    it('a refresh that finishes after sign-out cannot resurrect the session', async () => {
      let release!: (v: unknown) => void;
      const slow = new Promise((r) => (release = r));
      const f = vi
        .fn()
        .mockResolvedValueOnce(ok(tokens(fakeJwt(5), 'r1')))
        .mockReturnValueOnce(slow)
        .mockResolvedValue({ ok: true, status: 204 });
      const a = await load(f);
      await a.login('alice', 'pw');
      const pending = a.getToken().catch((e) => e);
      await a.logout();
      release(ok(tokens(fakeJwt(900), 'r-late')));
      expect(await pending).toBeInstanceOf(a.AuthRequiredError);
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('initAuth (page reload)', () => {
    const seed = () => sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ refreshToken: 'r-old', username: 'alice' }));

    it('restores the session from the stored refresh token', async () => {
      seed();
      const f = vi.fn().mockResolvedValue(ok(tokens(fakeJwt(900), 'r-new', 'operator')));
      const a = await load(f);
      const init = a.initAuth();
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'restoring', username: 'alice' });
      await init;
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-in', username: 'alice', role: 'operator' });
      expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ refresh_token: 'r-old' });
    });

    it('is idempotent', async () => {
      seed();
      const f = vi.fn().mockResolvedValue(ok(tokens()));
      const a = await load(f);
      await Promise.all([a.initAuth(), a.initAuth()]);
      expect(f).toHaveBeenCalledTimes(1);
    });

    it('drops a refresh token the server rejects', async () => {
      seed();
      const a = await load(vi.fn().mockResolvedValue(fail(401)));
      await a.initAuth();
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('keeps the stored token when the server is merely unreachable', async () => {
      seed();
      const a = await load(vi.fn().mockRejectedValue(new TypeError('offline')));
      await a.initAuth();
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-out' });
      expect(a.getAuthSnapshot().notice).toMatch(/could not reach/i);
      expect(sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();
    });

    it('starts signed out and makes no request when there is nothing stored', async () => {
      const f = vi.fn();
      const a = await load(f);
      await a.initAuth();
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      expect(f).not.toHaveBeenCalled();
    });

    it('ignores a corrupt stored value', async () => {
      sessionStorage.setItem(STORAGE_KEY, '{not json');
      const f = vi.fn();
      const a = await load(f);
      await a.initAuth();
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      expect(f).not.toHaveBeenCalled();
    });
  });

  describe('dev-only demo account', () => {
    const demo = { VITE_DEMO_USERNAME: 'demo_viewer', VITE_DEMO_PASSWORD: 'demo-pw' };

    it('signs in automatically in development when VITE_DEMO_* are set', async () => {
      const f = vi.fn().mockResolvedValue(ok(tokens()));
      const a = await load(f, { DEV: true, ...demo });
      await a.initAuth();
      expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ username: 'demo_viewer', password: 'demo-pw' });
      expect(a.getAuthSnapshot()).toMatchObject({ status: 'signed-in', username: 'demo_viewer' });
    });

    it('does NOT sign in with them when DEV is false (production build)', async () => {
      const f = vi.fn();
      const a = await load(f, { DEV: false, ...demo });
      await a.initAuth();
      expect(f).not.toHaveBeenCalled();
      expect(a.getAuthSnapshot().status).toBe('signed-out');
      await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
    });

    it('an explicit sign-out is not undone by the dev auto-login', async () => {
      const f = vi.fn().mockResolvedValue(ok(tokens()));
      const a = await load(f, { DEV: true, ...demo });
      await a.initAuth();
      await a.logout();
      await expect(a.getToken()).rejects.toBeInstanceOf(a.AuthRequiredError);
    });
  });

  describe('store', () => {
    it('keeps a stable snapshot until something changes, and notifies subscribers', async () => {
      const a = await load(vi.fn().mockResolvedValue(ok(tokens())));
      const first = a.getAuthSnapshot();
      expect(a.getAuthSnapshot()).toBe(first);
      const listener = vi.fn();
      const unsubscribe = a.subscribeAuth(listener);
      await a.login('alice', 'pw');
      expect(listener).toHaveBeenCalled();
      expect(a.getAuthSnapshot()).not.toBe(first);
      unsubscribe();
      listener.mockClear();
      await a.logout();
      expect(listener).not.toHaveBeenCalled();
    });
  });
});
