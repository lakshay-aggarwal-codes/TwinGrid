import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getToken, forceRefresh, AuthRequiredError } = vi.hoisted(() => ({
  getToken: vi.fn(),
  forceRefresh: vi.fn(),
  AuthRequiredError: class AuthRequiredError extends Error {},
}));

vi.mock("../authClient", () => ({ getToken: () => getToken(), forceRefresh: () => forceRefresh(), AuthRequiredError }));
vi.mock("@/lib/errorReporter.ts", () => ({ reportError: vi.fn() }));
vi.mock("../config", () => ({
  API_BASE_URL: "https://api.example.com",
  WS_LIVE_URL: "wss://api.example.com/ws/live",
  assertApiConfigured: () => {},
}));

import { connectWebSocket, fetchAlerts } from "./apiClient";

const json = (status: number, body: unknown) =>
  ({ ok: status < 400, status, statusText: "s", text: async () => JSON.stringify(body) }) as unknown as Response;

describe("authedFetch (via fetchAlerts)", () => {
  beforeEach(() => {
    getToken.mockReset().mockResolvedValue("tok-1");
    forceRefresh.mockReset().mockResolvedValue("tok-2");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the bearer token", async () => {
    const f = vi.fn().mockResolvedValue(json(200, []));
    vi.stubGlobal("fetch", f);
    await fetchAlerts();
    expect(f.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-1");
    expect(forceRefresh).not.toHaveBeenCalled();
  });

  it("on 401 refreshes once and retries with the new token", async () => {
    const f = vi.fn().mockResolvedValueOnce(json(401, { detail: "Invalid or expired token" })).mockResolvedValueOnce(json(200, [{ id: 1 }]));
    vi.stubGlobal("fetch", f);
    await expect(fetchAlerts()).resolves.toEqual([{ id: 1 }]);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
    expect(f.mock.calls[1][1].headers.Authorization).toBe("Bearer tok-2");
  });

  it("does not loop: a second 401 surfaces as an error after one retry", async () => {
    const f = vi.fn().mockResolvedValue(json(401, { detail: "nope" }));
    vi.stubGlobal("fetch", f);
    await expect(fetchAlerts()).rejects.toMatchObject({ status: 401 });
    expect(f).toHaveBeenCalledTimes(2);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
  });

  it("propagates AuthRequiredError when the session is gone", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, {})));
    forceRefresh.mockRejectedValue(new AuthRequiredError());
    await expect(fetchAlerts()).rejects.toBeInstanceOf(AuthRequiredError);
  });

  it("does not treat 403 as an auth failure (viewer calling an operator route)", async () => {
    const f = vi.fn().mockResolvedValue(json(403, { detail: "Operator role required" }));
    vi.stubGlobal("fetch", f);
    await expect(fetchAlerts()).rejects.toMatchObject({ status: 403 });
    expect(forceRefresh).not.toHaveBeenCalled();
    expect(f).toHaveBeenCalledTimes(1);
  });
});

class FakeWS {
  static instances: FakeWS[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  serverClose(code: number) {
    this.onclose?.({ code });
  }
  serverSend(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
}

const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

describe("connectWebSocket", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWS.instances = [];
    getToken.mockReset().mockResolvedValue("tok-1");
    vi.stubGlobal("WebSocket", FakeWS);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("connects with the current access token in the query string", async () => {
    connectWebSocket(() => {});
    await flush();
    expect(FakeWS.instances[0].url).toBe("wss://api.example.com/ws/live?token=tok-1");
  });

  it("reconnects immediately with a FRESH token when the server closes with 4002 (token expired)", async () => {
    connectWebSocket(() => {});
    await flush();
    getToken.mockResolvedValue("tok-2");
    FakeWS.instances[0].serverClose(4002);
    await vi.advanceTimersByTimeAsync(10);
    expect(FakeWS.instances).toHaveLength(2);
    expect(FakeWS.instances[1].url).toContain("token=tok-2");
  });

  it("backs off on other closes and does NOT reset the backoff just because the socket opened (cap rejection)", async () => {
    connectWebSocket(() => {});
    await flush();
    for (const expectedWait of [3000, 4500, 6750]) {
      const before = FakeWS.instances.length;
      const sock = FakeWS.instances[before - 1];
      sock.onopen?.(); // accepted...
      sock.serverClose(4003); // ...then closed by the server: connection limit
      await vi.advanceTimersByTimeAsync(expectedWait - 1);
      expect(FakeWS.instances).toHaveLength(before); // not yet
      await vi.advanceTimersByTimeAsync(2);
      expect(FakeWS.instances).toHaveLength(before + 1);
    }
  });

  it("resets the backoff once the server actually streams", async () => {
    const received = vi.fn();
    connectWebSocket(received);
    await flush();
    FakeWS.instances[0].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001); // delay now 4500
    FakeWS.instances[1].serverSend({ pue: 1.3 });
    expect(received).toHaveBeenCalledWith({ pue: 1.3 });
    FakeWS.instances[1].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("stops reconnecting when there is no session any more", async () => {
    connectWebSocket(() => {});
    await flush();
    getToken.mockRejectedValue(new AuthRequiredError());
    FakeWS.instances[0].serverClose(4002);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("disconnect() closes the socket and cancels a pending reconnect", async () => {
    const { disconnect } = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1006);
    disconnect();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWS.instances).toHaveLength(1);

    const second = connectWebSocket(() => {});
    await flush();
    second.disconnect();
    expect(FakeWS.instances[1].closed).toBe(true);
  });
});
