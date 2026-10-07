import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getToken, forceRefresh, AuthRequiredError, reportError } = vi.hoisted(() => ({
  getToken: vi.fn(),
  forceRefresh: vi.fn(),
  AuthRequiredError: class AuthRequiredError extends Error {},
  reportError: vi.fn(),
}));

vi.mock("../authClient", () => ({ getToken: () => getToken(), forceRefresh: () => forceRefresh(), AuthRequiredError }));
vi.mock("@/lib/errorReporter.ts", () => ({ reportError }));
vi.mock("../config", () => ({
  API_BASE_URL: "https://api.example.com",
  WS_LIVE_URL: "wss://api.example.com/ws/live",
  assertApiConfigured: () => {},
}));

import { connectWebSocket, probeHealthz } from "./wsTransport.ts";
import { validState } from "./testFixtures";

class FakeWS {
  static instances: FakeWS[] = [];
  onmessage: ((e: { data: unknown }) => void) | null = null;
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
const last = () => FakeWS.instances[FakeWS.instances.length - 1];

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.instances = [];
  getToken.mockReset().mockResolvedValue("tok-1");
  forceRefresh.mockReset().mockResolvedValue("tok-2");
  reportError.mockReset();
  fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("WebSocket", FakeWS);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("connectWebSocket", () => {
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
    expect(forceRefresh).toHaveBeenCalledTimes(1);
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

  it("4005 (inbound rate limit) also backs off", async () => {
    connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(4005);
    await vi.advanceTimersByTimeAsync(2999);
    expect(FakeWS.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2);
    expect(FakeWS.instances).toHaveLength(2);
  });

  it("resets the backoff only once a VALID frame arrives", async () => {
    const received = vi.fn();
    connectWebSocket(received);
    await flush();
    FakeWS.instances[0].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001); // delay now 4500
    FakeWS.instances[1].serverSend(validState());
    expect(received).toHaveBeenCalledTimes(1);
    FakeWS.instances[1].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("an invalid frame is dropped and reported, and does NOT reset the backoff", async () => {
    const received = vi.fn();
    connectWebSocket(received);
    await flush();
    FakeWS.instances[0].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001); // delay now 4500
    FakeWS.instances[1].serverSend({ pue: 1.3 }); // breaks the contract
    expect(received).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledWith(expect.stringContaining("contract.ws.live"), expect.anything());
    FakeWS.instances[1].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001);
    expect(FakeWS.instances).toHaveLength(2); // still waiting: next delay is 4500
    await vi.advanceTimersByTimeAsync(1500);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("drops malformed JSON and non-text frames without delivering them", async () => {
    const received = vi.fn();
    connectWebSocket(received);
    await flush();
    FakeWS.instances[0].onmessage?.({ data: "{not json" });
    FakeWS.instances[0].onmessage?.({ data: new ArrayBuffer(4) });
    expect(received).not.toHaveBeenCalled();
    expect(reportError).toHaveBeenCalledTimes(2);
  });

  it("delivers a valid frame with unknown enum values as raw strings", async () => {
    const received = vi.fn();
    connectWebSocket(received);
    await flush();
    FakeWS.instances[0].serverSend(
      validState({ origin: "measured", cooling_mode: "liquid", anomaly_status: { status: "recalibrating", message: "m" } })
    );
    const frame = received.mock.calls[0][0];
    expect(frame.origin).toBe("measured");
    expect(frame.cooling_mode).toBe("liquid");
    expect(frame.anomaly_status.status).toBe("recalibrating");
    expect(frame.anomaly_status.score).toBeNull();
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

describe("close codes", () => {
  it("4001: refreshes once and retries; a second 4001 stops and surfaces 'unauthenticated'", async () => {
    const conn = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(4001);
    await vi.advanceTimersByTimeAsync(10);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
    expect(FakeWS.instances).toHaveLength(2);
    FakeWS.instances[1].serverClose(4001);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWS.instances).toHaveLength(2);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
    expect(conn.getState()).toMatchObject({ status: "closed", reason: "unauthenticated", lastCloseCode: 4001 });
  });

  it("4001 stops at once when the refresh itself says the session is gone", async () => {
    const conn = connectWebSocket(() => {});
    await flush();
    forceRefresh.mockRejectedValue(new AuthRequiredError());
    FakeWS.instances[0].serverClose(4001);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(conn.getState().reason).toBe("unauthenticated");
  });

  it("a valid frame re-arms the refresh, so a later 4002 refreshes again", async () => {
    connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(4002);
    await vi.advanceTimersByTimeAsync(10);
    FakeWS.instances[1].serverSend(validState());
    FakeWS.instances[1].serverClose(4002);
    await vi.advanceTimersByTimeAsync(10);
    expect(forceRefresh).toHaveBeenCalledTimes(2);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("repeated 4002 with no valid frame in between backs off instead of spinning", async () => {
    connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(4002);
    await vi.advanceTimersByTimeAsync(10);
    FakeWS.instances[1].serverClose(4002);
    await vi.advanceTimersByTimeAsync(10);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
    expect(FakeWS.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(3001);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("4004: stops permanently as 'forbidden_origin'", async () => {
    const conn = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(4004);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(forceRefresh).not.toHaveBeenCalled();
    expect(conn.getState()).toMatchObject({ status: "closed", reason: "forbidden_origin", lastCloseCode: 4004 });
  });

  it("1009: stops (client bug)", async () => {
    const conn = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1009);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(FakeWS.instances).toHaveLength(1);
    expect(conn.getState()).toMatchObject({ status: "closed", reason: "message_too_large" });
  });
});

describe("transport state", () => {
  it("never reports a feed as streaming from the socket opening alone", async () => {
    const states: string[] = [];
    const conn = connectWebSocket(
      () => {},
      undefined,
      (s) => states.push(s.status)
    );
    await flush();
    FakeWS.instances[0].onopen?.();
    expect(conn.getState().status).toBe("open");
    expect(conn.getState().attempt).toBe(0);
    FakeWS.instances[0].serverClose(4003);
    await vi.advanceTimersByTimeAsync(3001);
    last().onopen?.();
    expect(conn.getState().attempt).toBe(1); // open did not clear the failure count
    last().serverSend(validState());
    expect(conn.getState().attempt).toBe(0); // the valid frame did
    expect(states).toContain("reconnecting");
  });

  it("exposes attempt, lastCloseCode and nextRetryAt while waiting", async () => {
    vi.setSystemTime(1_000_000);
    const conn = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1006);
    expect(conn.getState()).toMatchObject({ status: "reconnecting", attempt: 1, lastCloseCode: 1006, nextRetryAt: 1_003_000 });
  });

  it("keeps the legacy onStatus contract: connecting -> open -> closed", async () => {
    const seen: string[] = [];
    connectWebSocket(() => {}, (s) => seen.push(s));
    await flush();
    FakeWS.instances[0].onopen?.();
    FakeWS.instances[0].serverClose(1006);
    expect(seen).toEqual(["connecting", "open", "closed"]);
  });

  it("does not call onStatus after an explicit disconnect()", async () => {
    const seen: string[] = [];
    const { disconnect } = connectWebSocket(() => {}, (s) => seen.push(s));
    await flush();
    disconnect();
    expect(seen).toEqual(["connecting"]);
  });
});

describe("backend-unavailable probe", () => {
  it("after repeated failures calls unauthenticated /healthz and maps 503 to 'unavailable'", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 503 });
    const conn = connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1006);
    await vi.advanceTimersByTimeAsync(3001);
    FakeWS.instances[1].serverClose(1006); // second consecutive failure
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.com/healthz");
    expect(fetchMock.mock.calls[0][1]?.headers).toBeUndefined(); // no Authorization
    expect(conn.getState().backend).toBe("unavailable");
  });

  it("does not probe on the first failure", async () => {
    connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1006);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("probeHealthz maps outcomes", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200 });
    await expect(probeHealthz()).resolves.toBe("reachable");
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });
    await expect(probeHealthz()).resolves.toBe("unavailable");
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(probeHealthz()).resolves.toBe("unknown");
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(probeHealthz()).resolves.toBe("unreachable");
  });
});

describe("secrets", () => {
  it("never passes the token to reportError messages it builds itself", async () => {
    connectWebSocket(() => {});
    await flush();
    FakeWS.instances[0].serverClose(1006);
    expect(JSON.stringify(reportError.mock.calls)).not.toContain("tok-1");
  });
});
