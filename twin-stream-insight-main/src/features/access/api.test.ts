import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activateAccount, fetchRequestStatus, resendActivation, submitAccessRequest } from './api';
import * as fx from '@/contract/fixtures-access';

const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('submitAccessRequest', () => {
  it('POSTs the trimmed fields to /api/access-requests and returns the validated body', async () => {
    fetchMock.mockResolvedValue(reply(202, fx.accessRequestCreated));
    const r = await submitAccessRequest({ name: ' Ada ', email: ' ada@example.com ', purpose: ' look ' });
    expect(r).toEqual({ kind: 'ok', data: expect.objectContaining({ ref: 'AR-7K3Q9X', status: 'pending' }) });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/access-requests$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ name: 'Ada', email: 'ada@example.com', purpose: 'look' });
  });
  it('maps 422, 429, network failure and a malformed 202', async () => {
    fetchMock.mockResolvedValueOnce(reply(422, fx.invalidRequest));
    expect(await submitAccessRequest({ name: 'a', email: 'a@b.co', purpose: '' })).toEqual({ kind: 'invalid' });
    fetchMock.mockResolvedValueOnce(reply(429, {}));
    expect(await submitAccessRequest({ name: 'a', email: 'a@b.co', purpose: '' })).toEqual({ kind: 'rate_limited' });
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    expect(await submitAccessRequest({ name: 'a', email: 'a@b.co', purpose: '' })).toEqual({ kind: 'offline' });
    fetchMock.mockResolvedValueOnce(reply(202, { nope: true }));
    expect(await submitAccessRequest({ name: 'a', email: 'a@b.co', purpose: '' })).toEqual({ kind: 'unexpected' });
  });
});

describe('fetchRequestStatus', () => {
  it('GETs /{ref}/status with the X-Request-Token header', async () => {
    fetchMock.mockResolvedValue(reply(200, fx.statusApproved));
    const r = await fetchRequestStatus('AR-7K3Q9X', 'tok');
    expect(r).toEqual({ kind: 'ok', data: expect.objectContaining({ status: 'approved', can_activate: true }) });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/access-requests\/AR-7K3Q9X\/status$/);
    expect(init.method).toBe('GET');
    expect(init.headers['X-Request-Token']).toBe('tok');
    expect(init.body).toBeUndefined();
  });
  it('validates every documented status', async () => {
    for (const body of [fx.statusPending, fx.statusApproved, fx.statusActivated, fx.statusRejected, fx.statusExpired]) {
      fetchMock.mockResolvedValueOnce(reply(200, body));
      const r = await fetchRequestStatus('AR-7K3Q9X', 'tok');
      expect(r.kind).toBe('ok');
    }
  });
  it('404 is not_found; an unknown status or a 500 is unexpected; offline is offline', async () => {
    fetchMock.mockResolvedValueOnce(reply(404, fx.notFound));
    expect(await fetchRequestStatus('x', 'y')).toEqual({ kind: 'not_found' });
    fetchMock.mockResolvedValueOnce(reply(200, { ...fx.statusPending, status: 'banana' }));
    expect(await fetchRequestStatus('x', 'y')).toEqual({ kind: 'unexpected' });
    fetchMock.mockResolvedValueOnce(reply(500, {}));
    expect(await fetchRequestStatus('x', 'y')).toEqual({ kind: 'unexpected' });
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    expect(await fetchRequestStatus('x', 'y')).toEqual({ kind: 'offline' });
  });
  it('encodes the ref in the path', async () => {
    fetchMock.mockResolvedValue(reply(404, fx.notFound));
    await fetchRequestStatus('a/b', 'y');
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/access-requests/a%2Fb/status');
  });
});

describe('resendActivation', () => {
  it('POSTs {ref, status_token} and accepts the neutral 202', async () => {
    fetchMock.mockResolvedValue(reply(202, fx.resendAck));
    expect(await resendActivation('AR-7K3Q9X', 'tok')).toEqual({ kind: 'ok' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/access-requests\/resend-activation$/);
    expect(JSON.parse(init.body)).toEqual({ ref: 'AR-7K3Q9X', status_token: 'tok' });
  });
});

describe('activateAccount', () => {
  it('POSTs {token, password}; 200 is ok', async () => {
    fetchMock.mockResolvedValue(reply(200, fx.activateOk));
    expect(await activateAccount('t', 'pw-pw-pw-pw-pw')).toEqual({ kind: 'ok' });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ token: 't', password: 'pw-pw-pw-pw-pw' });
  });
  it('400 invalid_or_expired, 422 invalid, 429 rate limited', async () => {
    fetchMock.mockResolvedValueOnce(reply(400, fx.activateInvalid));
    expect(await activateAccount('t', 'p')).toEqual({ kind: 'invalid_or_expired' });
    fetchMock.mockResolvedValueOnce(reply(422, {}));
    expect(await activateAccount('t', 'p')).toEqual({ kind: 'invalid' });
    fetchMock.mockResolvedValueOnce(reply(429, {}));
    expect(await activateAccount('t', 'p')).toEqual({ kind: 'rate_limited' });
  });
  it('does not put the password in the URL or headers', async () => {
    fetchMock.mockResolvedValue(reply(200, fx.activateOk));
    await activateAccount('tok-in-body', 'hunter2-hunter2');
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain('hunter2');
    expect(JSON.stringify(init.headers)).not.toContain('hunter2');
  });
});
