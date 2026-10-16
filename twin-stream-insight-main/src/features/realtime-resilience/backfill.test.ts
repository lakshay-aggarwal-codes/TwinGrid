import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { fetchTelemetrySamples } from "@/api/apiClient";
import { createFeedStore, type FeedStore } from "@/telemetry/feedStore";
import { fakeClock, fakeTransport, liveFrame, transportState } from "@/telemetry/testUtils";
import {
  BACKFILL_PAGE_LIMIT,
  MAX_BACKFILL_WINDOW_MS,
  createBackfiller,
  gapBetween,
  recoveredFrames,
  type BackfillDeps,
  type FrameMark,
} from "./backfill";
import { backfillLine } from "./backfillText";

const T0 = Date.parse("2026-01-01T12:00:00Z");
const mark = (seq: number | null, offsetMs: number | null): FrameMark => ({ seq, tsIngestMs: offsetMs === null ? null : T0 + offsetMs });
const at = (offsetMs: number) => new Date(T0 + offsetMs).toISOString();

describe("gapBetween (pure)", () => {
  it("is null for contiguous frames, duplicates and the very first frame", () => {
    expect(gapBetween(null, mark(5, 0))).toBeNull();
    expect(gapBetween(mark(5, 0), mark(6, 3000))).toBeNull();
    expect(gapBetween(mark(5, 0), mark(5, 3000))).toBeNull();
  });

  it("is null after a server restart (seq went backwards): the window is unknown", () => {
    expect(gapBetween(mark(50, 0), mark(2, 60_000))).toBeNull();
  });

  it("is null when seq or ts_ingest is missing on either frame", () => {
    expect(gapBetween(mark(null, 0), mark(9, 9000))).toBeNull();
    expect(gapBetween(mark(5, 0), mark(null, 9000))).toBeNull();
    expect(gapBetween(mark(5, null), mark(9, 9000))).toBeNull();
    expect(gapBetween(mark(5, 0), mark(9, null))).toBeNull();
  });

  it("bounds the window by the two frames' server times and counts the missed frames", () => {
    expect(gapBetween(mark(10, 0), mark(14, 12_000))).toEqual({
      from: at(1),
      to: at(12_000),
      missedFrames: 3,
      truncated: false,
    });
  });

  it("is null when server time does not advance", () => {
    expect(gapBetween(mark(10, 5000), mark(14, 5000))).toBeNull();
  });

  it("caps the window at one hour and says so", () => {
    const gap = gapBetween(mark(10, 0), mark(5000, 4 * 3_600_000));
    expect(gap).not.toBeNull();
    expect(Date.parse(gap!.to) - Date.parse(gap!.from)).toBe(MAX_BACKFILL_WINDOW_MS);
    expect(gap!.truncated).toBe(true);
    expect(gap!.missedFrames).toBe(4989);
  });
});

describe("backfillLine", () => {
  const w = { from: at(1), to: at(12_000), missedFrames: 3, truncated: false };
  it("says nothing while idle", () => expect(backfillLine({ status: "idle" })).toBeNull());
  it("says what is loading", () => expect(backfillLine({ status: "loading", window: w })?.text).toBe("Backfilling 3 missed updates…"));
  it("says history is unavailable instead of pretending", () =>
    expect(backfillLine({ status: "unavailable", window: w })).toEqual({
      state: "unavailable",
      text: "3 updates missed; stored history unavailable",
    }));
  it("reports a full recovery", () =>
    expect(backfillLine({ status: "done", window: w, series: [], recovered: 3, moreAvailable: false })?.text).toBe(
      "Backfilled 3 missed updates from stored history"
    ));
  it("states a shortfall and the caps", () =>
    expect(backfillLine({ status: "done", window: { ...w, truncated: true }, series: [], recovered: 1, moreAvailable: true })?.text).toBe(
      "Backfilled 1 of 3 missed updates (the rest were not stored); oldest part of the gap not requested; more stored data exists than was loaded"
    ));
});

describe("recoveredFrames", () => {
  it("counts valid samples per sensor and ignores invalid ones", () => {
    const s = (quality: string) => ({ ts_event: at(1), value: 1, quality });
    expect(recoveredFrames([{ measurand: "a", sensorId: "x", samples: [s("ok"), s("invalid"), s("ok")] }])).toBe(2);
    expect(recoveredFrames([])).toBe(0);
  });
});

// ------------------------------------------------------------------------------------------------ with a real feed store

type SamplesFn = typeof fetchTelemetrySamples;

function page(sensorId: string, offsetsMs: number[], next: string | null = null) {
  return {
    external_id: sensorId,
    unit: "u",
    sampling_interval_s: 3,
    stream: "live",
    quality: "any",
    items: offsetsMs.map((o) => ({ ts_event: at(o), value: 1, quality: "ok", origin: "simulated" })),
    next_cursor: next,
  };
}

const flush = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
};

describe("createBackfiller on a feed store (fake timers)", () => {
  let clock: ReturnType<typeof fakeClock>;
  let t: ReturnType<typeof fakeTransport>;
  let store: FeedStore;
  let samples: Mock<SamplesFn>;
  let facilityId: Mock<BackfillDeps["facilityId"]>;
  let deps: BackfillDeps;

  const open = () => t.h.onStatus!("open");
  const send = (seq: number | undefined, offsetMs: number) =>
    t.h.onMessage!(liveFrame({ seq, ts_ingest: at(offsetMs), origin: "simulated" }));
  const state = () => store.getView().freshness.state;
  const tick = (ms: number) => {
    clock.advance(ms);
    vi.advanceTimersByTime(ms);
  };

  beforeEach(() => {
    vi.useFakeTimers();
    clock = fakeClock();
    t = fakeTransport();
    store = createFeedStore({ connect: t.connect, clock });
    facilityId = vi.fn<BackfillDeps["facilityId"]>().mockResolvedValue(7);
    samples = vi.fn<SamplesFn>(async (sensorId) => page(sensorId, [3000, 6000, 9000]));
    deps = { facilityId, samples };
    store.start();
  });
  afterEach(() => {
    store.stop();
    vi.useRealTimers();
  });

  it("live -> stale -> disconnected -> reconnecting -> live, then backfills exactly the missed window", async () => {
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    expect(state()).toBe("live");
    expect(b.getState().status).toBe("idle");

    tick(10_000);
    expect(state()).toBe("stale");
    t.h.onStatus!("closed");
    expect(state()).toBe("disconnected");
    t.h.onTransport!(transportState({ status: "reconnecting", attempt: 1 }));
    expect(state()).toBe("reconnecting");
    t.h.onStatus!("connecting");
    open();
    expect(state()).toBe("reconnecting"); // an open socket alone is not live, so nothing is backfilled yet
    expect(b.getState().status).toBe("idle");

    send(14, 12_000); // first valid frame after the reconnect: server numbered 11, 12, 13 in between
    expect(state()).toBe("live");
    expect(b.getState()).toMatchObject({ status: "loading", window: { missedFrames: 3, truncated: false } });
    await flush();

    expect(facilityId).toHaveBeenCalledTimes(1);
    expect(samples).toHaveBeenCalledTimes(5); // the five measurands
    const [sensorId, params] = samples.mock.calls[0];
    expect(sensorId).toBe("fac7.water_flow_lpm");
    expect(params).toEqual({ from: at(1), to: at(12_000), limit: BACKFILL_PAGE_LIMIT });
    const done = b.getState();
    expect(done.status).toBe("done");
    if (done.status === "done") {
      expect(done.recovered).toBe(3);
      expect(done.series).toHaveLength(5);
      expect(done.moreAvailable).toBe(false);
    }
    b.stop();
  });

  it("does not backfill contiguous frames, a restart, or frames without seq", async () => {
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    send(11, 3000);
    send(2, 6000); // restart
    send(undefined, 9000); // unordered: no seq
    await flush();
    expect(samples).not.toHaveBeenCalled();
    expect(b.getState().status).toBe("idle");
    b.stop();
  });

  it("reports unavailable (and does not retry) when the history API fails", async () => {
    samples.mockRejectedValue(new Error("404"));
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    send(13, 9000);
    await flush();
    expect(b.getState()).toMatchObject({ status: "unavailable", window: { missedFrames: 2 } });
    expect(samples).toHaveBeenCalledTimes(5);
    tick(60_000);
    await flush();
    expect(samples).toHaveBeenCalledTimes(5);
    b.stop();
  });

  it("still reports what it could read when only some sensors fail, and flags a truncated page", async () => {
    samples.mockImplementation(async (sensorId) => {
      if (sensorId.endsWith("humidity_pct")) throw new Error("boom");
      return page(sensorId, [3000], "more");
    });
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    send(13, 9000);
    await flush();
    const s = b.getState();
    expect(s.status).toBe("done");
    if (s.status === "done") {
      expect(s.series).toHaveLength(4);
      expect(s.recovered).toBe(1); // 1 of the 2 missed frames: the shortfall is not hidden
      expect(s.moreAvailable).toBe(true);
    }
    b.stop();
  });

  it("a newer gap supersedes a request still in flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    samples.mockImplementationOnce(async (id) => {
      await gate;
      return page(id, [3000]);
    });
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    send(13, 9000); // gap 1 (one of its five requests is held)
    await flush();
    expect(b.getState().status).toBe("loading");
    send(20, 30_000); // gap 2 supersedes gap 1
    await flush();
    release();
    await flush();
    const s = b.getState();
    expect(s.status).toBe("done");
    if (s.status === "done") expect(s.window.missedFrames).toBe(6);
    b.stop();
  });

  it("stop() resets to idle, detaches from the feed and ignores a late result", async () => {
    const b = createBackfiller(store, deps);
    b.start();
    open();
    send(10, 0);
    send(13, 9000);
    b.stop();
    await flush();
    expect(b.getState().status).toBe("idle");
    send(20, 30_000);
    await flush();
    expect(b.getState().status).toBe("idle");
  });

  it("notifies subscribers on each transition", async () => {
    const b = createBackfiller(store, deps);
    const seen: string[] = [];
    b.subscribe(() => seen.push(b.getState().status));
    b.start();
    open();
    send(10, 0);
    send(13, 9000);
    await flush();
    expect(seen).toEqual(["loading", "done"]);
    b.stop();
  });
});

describe("feed store passes the jitter source to the transport", () => {
  it("defaults to Math.random and accepts an override", () => {
    const calls: unknown[][] = [];
    const connect = ((...args: unknown[]) => {
      calls.push(args);
      return { disconnect: () => {}, getState: () => transportState() };
    }) as unknown as typeof import("@/api/apiClient").connectWebSocket;
    const random = () => 0.1;
    const a = createFeedStore({ connect, random });
    a.start();
    const b = createFeedStore({ connect });
    b.start();
    expect((calls[0][3] as { random: () => number }).random).toBe(random);
    expect((calls[1][3] as { random: () => number }).random).toBe(Math.random);
    a.stop();
    b.stop();
  });
});
