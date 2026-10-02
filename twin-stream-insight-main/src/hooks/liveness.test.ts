import { describe, it, expect } from "vitest";
import {
  DEFAULT_INTERVAL_S,
  MIN_STALE_AFTER_MS,
  STALE_INTERVAL_MULTIPLIER,
  deriveLiveness,
  originBanner,
  staleAfterMs,
} from "./liveness.ts";

const W = staleAfterMs(3);

describe("staleAfterMs", () => {
  it("is a multiple of the payload interval", () => {
    expect(staleAfterMs(3)).toBe(3 * 1000 * STALE_INTERVAL_MULTIPLIER);
    expect(staleAfterMs(10)).toBe(30_000);
  });
  it("never goes below the floor", () => {
    expect(staleAfterMs(0.5)).toBe(MIN_STALE_AFTER_MS);
  });
  it("falls back to the default interval for missing or invalid values", () => {
    const fallback = staleAfterMs(DEFAULT_INTERVAL_S);
    for (const v of [undefined, null, 0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(staleAfterMs(v)).toBe(fallback);
    }
  });
});

describe("deriveLiveness", () => {
  const base = { staleAfterMs: W };

  it("is connecting before the first payload while the socket is connecting or open", () => {
    expect(deriveLiveness({ ...base, socket: "connecting", lastMessageAt: null, now: 1000 })).toBe("connecting");
    expect(deriveLiveness({ ...base, socket: "open", lastMessageAt: null, now: 1000 })).toBe("connecting");
  });
  it("is disconnected if the socket closed before any payload arrived", () => {
    expect(deriveLiveness({ ...base, socket: "closed", lastMessageAt: null, now: 1000 })).toBe("disconnected");
  });
  it("is live while the socket is open and the last payload is fresh", () => {
    expect(deriveLiveness({ ...base, socket: "open", lastMessageAt: 1000, now: 1000 + W })).toBe("live");
  });
  it("turns stale once the last payload is older than the window (silent drop)", () => {
    expect(deriveLiveness({ ...base, socket: "open", lastMessageAt: 1000, now: 1000 + W + 1 })).toBe("stale");
  });
  it("is disconnected as soon as the socket is not open, however fresh the last payload", () => {
    expect(deriveLiveness({ ...base, socket: "closed", lastMessageAt: 1000, now: 1001 })).toBe("disconnected");
  });
  it("stays disconnected (not connecting) while re-connecting after an earlier payload", () => {
    expect(deriveLiveness({ ...base, socket: "connecting", lastMessageAt: 1000, now: 1001 })).toBe("disconnected");
  });
});

describe("originBanner", () => {
  it("labels an explicit simulated origin and says timestamps are not event time", () => {
    const b = originBanner("simulated");
    expect(b.tone).toBe("simulated");
    expect(b.label).toBe("Simulated");
    expect(b.title).toMatch(/not event time/i);
  });
  it("shows a missing origin as an unverified source", () => {
    for (const v of [undefined, null, ""]) {
      const b = originBanner(v);
      expect(b.tone).toBe("unverified");
      expect(b.label).toBe("Unverified source");
    }
  });
  it("never presents an unrecognised origin as measured", () => {
    const b = originBanner("measured");
    expect(b.tone).toBe("unverified");
    expect(b.label.toLowerCase()).not.toContain("measured");
  });
});
