import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function fakeJwt(expSecondsFromNow: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `h.${payload}.s`;
}

describe('authClient.getToken', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/');
    vi.stubEnv('VITE_DEMO_USERNAME', 'demo');
    vi.stubEnv('VITE_DEMO_PASSWORD', 'pw');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('can retry after a failed login (inFlight is reset)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, statusText: 'Service Unavailable' })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: fakeJwt(3600) }) });
    vi.stubGlobal('fetch', fetchMock);
    const { getToken } = await import('./authClient');

    await expect(getToken()).rejects.toThrow(/Login failed: 503/);
    await expect(getToken()).resolves.toMatch(/^h\./);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('posts to the shared base URL without a double slash', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ access_token: fakeJwt(3600) }) });
    vi.stubGlobal('fetch', fetchMock);
    const { getToken } = await import('./authClient');
    await getToken();
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.example.com/auth/login');
  });

  it('shares one login request between concurrent callers', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ access_token: fakeJwt(3600) }) });
    vi.stubGlobal('fetch', fetchMock);
    const { getToken } = await import('./authClient');
    await Promise.all([getToken(), getToken(), getToken()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
