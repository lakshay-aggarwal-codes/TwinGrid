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

import { JITTER_SPREAD, connectWebSocket, jitteredDelay } from "./wsTransport.ts";

class FakeWS {
  static instances: FakeWS[] = [];
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  close() {}
  serverClose(code: number) {
    this.onclose?.({ code });
  }
}

const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

beforeEach(() => {
  vi.useFakeTimers();
  FakeWS.instances = [];
  getToken.mockReset().mockResolvedValue("tok-1");
  forceRefresh.mockReset().mockResolvedValue("tok-2");
  reportError.mockReset();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200 }));
  vi.stubGlobal("WebSocket", FakeWS);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("jitteredDelay", () => {
  it("spans +-25% of the base and is exact at the midpoint", () => {
    expect(JITTER_SPREAD).toBe(0.5);
    expect(jitteredDelay(4000, () => 0)).toBe(3000);
    expect(jitteredDelay(4000, () => 0.5)).toBe(4000);
    expect(jitteredDelay(4000, () => 1)).toBe(5000);
  });

  it("clamps a misbehaving random source into [0, 1]", () => {
    expect(jitteredDelay(4000, () => -3)).toBe(3000);
    expect(jitteredDelay(4000, () => 9)).toBe(5000);
  });
});

describe("connectWebSocket retry jitter (fake timers)", () => {
  async function waitOf(random: (() => number) | undefined, close: number): Promise<number> {
    connectWebSocket(() => {}, undefined, undefined, random ? { random } : {});
    await flush();
    const before = FakeWS.instances.length;
    FakeWS.instances[before - 1].serverClose(close);
    // Find the first millisecond at which the retry fires.
    let waited = 0;
    while (FakeWS.instances.length === before && waited < 10_000) {
      await vi.advanceTimersByTimeAsync(1);
      waited += 1;
    }
    return waited;
  }

  it("without a random source the schedule is the plain 3000 ms (unchanged)", async () => {
    expect(await waitOf(undefined, 1006)).toBe(3000);
  });

  it("the earliest retry is 75% of the base and the latest 125%", async () => {
    expect(await waitOf(() => 0, 1006)).toBe(2250);
    FakeWS.instances = [];
    expect(await waitOf(() => 1, 1006)).toBe(3750);
  });

  it("jitter scales the growing base, not a fixed constant", async () => {
    connectWebSocket(() => {}, undefined, undefined, { random: () => 0 });
    await flush();
    FakeWS.instances[0].serverClose(4003);
    await vi.advanceTimersByTimeAsync(2250 + 1); // first retry at 3000 * 0.75
    expect(FakeWS.instances).toHaveLength(2);
    FakeWS.instances[1].serverClose(4003);
    await vi.advanceTimersByTimeAsync(3375 - 1); // base is now 4500; 4500 * 0.75
    expect(FakeWS.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(2);
    expect(FakeWS.instances).toHaveLength(3);
  });

  it("nextRetryAt reports the jittered wait", async () => {
    vi.setSystemTime(1_000_000);
    const conn = connectWebSocket(() => {}, undefined, undefined, { random: () => 0 });
    await flush();
    FakeWS.instances[0].serverClose(1006);
    expect(conn.getState()).toMatchObject({ status: "reconnecting", nextRetryAt: 1_002_250 });
  });
});
