import { describe, expect, it } from "vitest";
import type { AlertRecord } from "@/api/models";
import type { TelemetryGap, TelemetrySample, TelemetrySamplesPage } from "@/telemetry/history/schema";
import { MEASURANDS } from "@/telemetry/history/model";
import type { HistoryData } from "@/telemetry/history/useTelemetryHistory";
import { buildReplaySeries, compareSnapshots, datasetSpan, hasAnyData, lastAtOrBefore, readAt, snapshotAt, staleAfterFor, type ReplayDataset } from "./dataset";
import { buildPath, valueDomain } from "./chartGeometry";
import { loadReplay } from "./loader";
import { clamp, fractionOf, initialState, isReplaying, msAtFraction, replayReducer, scrubKeyTarget, windowFor, type ReplayState } from "./model";
import { alertPins, neighbourPin, pinsMayBeIncomplete } from "./pins";
import { formatInstantParam, parseInstantParam, parseReplayUrl, withReplayParams } from "./url";

const T0 = Date.parse("2026-10-14T00:00:00Z");
const MIN = 60_000;
const HOUR = 3_600_000;
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");

const sample = (ms: number, value: number, over: Partial<TelemetrySample> = {}): TelemetrySample => ({
  ts_event: iso(ms),
  ts_ingest: iso(ms),
  value,
  origin: "simulated",
  stream_id: "live",
  quality: "ok",
  invalid_reason: null,
  ...over,
});

function history(items: TelemetrySample[], over: Partial<HistoryData> = {}): HistoryData {
  return { sensorId: "fac1.it_power_kw", unit: "kW", samplingIntervalS: 300, thresholdS: null, items, gaps: [], gapsTruncated: false, moreAvailable: false, pagesLoaded: 1, ...over };
}
const seriesOf = (items: TelemetrySample[], over: Partial<HistoryData> = {}) => buildReplaySeries("it_power_kw", 1, history(items, over));
const dsOf = (...s: ReturnType<typeof seriesOf>[]): ReplayDataset => ({ series: s });

const WINDOW = { fromMs: T0, toMs: T0 + HOUR };
const live = (): ReplayState => initialState(WINDOW);

describe("replay state machine", () => {
  it("starts live and is not replaying", () => {
    expect(live().mode).toBe("live");
    expect(live().cursorMs).toBeNull();
    expect(isReplaying(live())).toBe(false);
  });

  it("scrubbing leaves live, pauses a running replay, and clamps to the window", () => {
    const s1 = replayReducer(live(), { type: "scrub", ms: T0 + 10 * MIN });
    expect(s1.mode).toBe("paused");
    expect(s1.cursorMs).toBe(T0 + 10 * MIN);
    expect(isReplaying(s1)).toBe(true);
    const playing = replayReducer(s1, { type: "play" });
    expect(replayReducer(playing, { type: "scrub", ms: T0 - HOUR }).cursorMs).toBe(T0);
    expect(replayReducer(playing, { type: "scrub", ms: T0 + 9 * HOUR }).cursorMs).toBe(T0 + HOUR);
    expect(replayReducer(playing, { type: "scrub", ms: NaN })).toBe(playing);
    expect(replayReducer(playing, { type: "scrub", ms: T0 + MIN }).mode).toBe("paused");
  });

  it("play from live starts at the window start; play at the end restarts; pause only affects a running replay", () => {
    const p = replayReducer(live(), { type: "play" });
    expect(p.mode).toBe("playing");
    expect(p.cursorMs).toBe(T0);
    const atEnd = replayReducer(live(), { type: "scrub", ms: T0 + HOUR });
    expect(replayReducer(atEnd, { type: "play" }).cursorMs).toBe(T0);
    expect(replayReducer(p, { type: "pause" }).mode).toBe("paused");
    expect(replayReducer(live(), { type: "pause" }).mode).toBe("live");
    expect(replayReducer(p, { type: "toggle" }).mode).toBe("paused");
    expect(replayReducer(replayReducer(p, { type: "toggle" }), { type: "toggle" }).mode).toBe("playing");
  });

  it("does not play an empty window", () => {
    const empty = initialState({ fromMs: T0, toMs: T0 });
    expect(replayReducer(empty, { type: "play" }).mode).toBe("live");
  });

  it("tick advances the cursor by wall time times speed and stops at the end", () => {
    let s = replayReducer(replayReducer(live(), { type: "speed", speed: 60 }), { type: "play" });
    s = replayReducer(s, { type: "tick", wallDeltaMs: 500 });
    expect(s.cursorMs).toBe(T0 + 30_000);
    s = replayReducer(s, { type: "tick", wallDeltaMs: 1000 });
    expect(s.cursorMs).toBe(T0 + 90_000);
    // a very long frame counts as at most one second
    s = replayReducer(s, { type: "tick", wallDeltaMs: 600_000 });
    expect(s.cursorMs).toBe(T0 + 150_000);
    // reaching the end pauses exactly at the end
    const near = replayReducer(replayReducer(live(), { type: "scrub", ms: T0 + HOUR - 1000 }), { type: "play" });
    const done = replayReducer(replayReducer(near, { type: "speed", speed: 60 }), { type: "tick", wallDeltaMs: 100 });
    expect(done.mode).toBe("paused");
    expect(done.cursorMs).toBe(T0 + HOUR);
  });

  it("tick does nothing unless playing, and ignores zero or negative time", () => {
    const paused = replayReducer(live(), { type: "scrub", ms: T0 + MIN });
    expect(replayReducer(paused, { type: "tick", wallDeltaMs: 100 })).toBe(paused);
    const p = replayReducer(live(), { type: "play" });
    expect(replayReducer(p, { type: "tick", wallDeltaMs: 0 })).toBe(p);
    expect(replayReducer(p, { type: "tick", wallDeltaMs: -5 })).toBe(p);
  });

  it("accepts only the offered speeds (1x to 60x)", () => {
    expect(replayReducer(live(), { type: "speed", speed: 60 }).speed).toBe(60);
    expect(replayReducer(live(), { type: "speed", speed: 1 }).speed).toBe(1);
    const s = live();
    expect(replayReducer(s, { type: "speed", speed: 61 })).toBe(s);
    expect(replayReducer(s, { type: "speed", speed: 0 })).toBe(s);
  });

  it("LIVE returns to the live feed and drops the cursor", () => {
    const s = replayReducer(replayReducer(live(), { type: "scrub", ms: T0 + MIN }), { type: "live" });
    expect(s.mode).toBe("live");
    expect(s.cursorMs).toBeNull();
    expect(isReplaying(s)).toBe(false);
  });

  it("a new window clamps the cursor and compare time B, and rejects a backwards window", () => {
    let s = replayReducer(live(), { type: "scrub", ms: T0 + 50 * MIN });
    s = replayReducer(s, { type: "setB", ms: T0 + 55 * MIN });
    const moved = replayReducer(s, { type: "window", fromMs: T0, toMs: T0 + 20 * MIN });
    expect(moved.cursorMs).toBe(T0 + 20 * MIN);
    expect(moved.compareBMs).toBe(T0 + 20 * MIN);
    expect(replayReducer(s, { type: "window", fromMs: T0 + HOUR, toMs: T0 })).toBe(s);
  });

  it("compare mode toggles and B is clamped; null clears it", () => {
    let s = replayReducer(live(), { type: "compare", on: true });
    expect(s.compareOn).toBe(true);
    s = replayReducer(s, { type: "setB", ms: T0 + 5 * HOUR });
    expect(s.compareBMs).toBe(T0 + HOUR);
    expect(replayReducer(s, { type: "setB", ms: null }).compareBMs).toBeNull();
  });
});

describe("windows, fractions and scrub keys", () => {
  const NOW = Date.parse("2026-10-14T12:00:00.900Z");
  it("the default window ends now (whole seconds)", () => {
    const w = windowFor(null, 6, NOW);
    expect(w.toMs).toBe(Date.parse("2026-10-14T12:00:00Z"));
    expect(w.toMs - w.fromMs).toBe(6 * HOUR);
  });
  it("a ?t= in the past centres the window on t but never past now", () => {
    const t = Date.parse("2026-10-13T12:00:00Z");
    const w = windowFor(t, 6, NOW);
    expect(w.toMs).toBe(t + 3 * HOUR);
    expect(w.fromMs).toBe(t - 3 * HOUR);
    const recent = windowFor(Date.parse("2026-10-14T11:59:00Z"), 6, NOW);
    expect(recent.toMs).toBe(Date.parse("2026-10-14T12:00:00Z"));
  });
  it("hours are limited to 1..168", () => {
    expect(windowFor(null, 9999, NOW).toMs - windowFor(null, 9999, NOW).fromMs).toBe(168 * HOUR);
    expect(windowFor(null, 0, NOW).toMs - windowFor(null, 0, NOW).fromMs).toBe(HOUR);
  });
  it("fraction and ms round-trip and clamp", () => {
    expect(fractionOf(T0 + HOUR / 2, T0, T0 + HOUR)).toBe(0.5);
    expect(fractionOf(T0 - 1, T0, T0 + HOUR)).toBe(0);
    expect(fractionOf(T0, T0, T0)).toBe(0);
    expect(msAtFraction(0.25, T0, T0 + HOUR)).toBe(T0 + 15 * MIN);
    expect(msAtFraction(7, T0, T0 + HOUR)).toBe(T0 + HOUR);
    expect(clamp(5, 0, 3)).toBe(3);
  });
  it("keyboard steps the scrubber and ignores other keys", () => {
    expect(scrubKeyTarget("ArrowRight", T0, T0, T0 + HOUR)).toBe(T0 + HOUR / 100);
    expect(scrubKeyTarget("ArrowLeft", T0, T0, T0 + HOUR)).toBe(T0);
    expect(scrubKeyTarget("PageUp", T0, T0, T0 + HOUR)).toBe(T0 + HOUR / 10);
    expect(scrubKeyTarget("Home", T0 + MIN, T0, T0 + HOUR)).toBe(T0);
    expect(scrubKeyTarget("End", T0 + MIN, T0, T0 + HOUR)).toBe(T0 + HOUR);
    expect(scrubKeyTarget("a", T0, T0, T0 + HOUR)).toBeNull();
  });
});

describe("?t= URL", () => {
  it("parses RFC 3339 with Z or an offset", () => {
    expect(parseInstantParam("2026-10-14T08:00:00Z")).toBe(Date.parse("2026-10-14T08:00:00Z"));
    expect(parseInstantParam("2026-10-14T13:30:00+05:30")).toBe(Date.parse("2026-10-14T08:00:00Z"));
  });
  it("refuses a missing zone, an impossible date, and junk", () => {
    expect(parseInstantParam("2026-10-14T08:00:00")).toBeNull();
    expect(parseInstantParam("2026-02-30T08:00:00Z")).toBeNull();
    expect(parseInstantParam("2026-10-14T24:00:00Z")).toBeNull();
    expect(parseInstantParam("yesterday")).toBeNull();
    expect(parseInstantParam("")).toBeNull();
    expect(parseInstantParam(null)).toBeNull();
  });
  it("formats whole-second UTC and round-trips through the query string, keeping unrelated parameters", () => {
    expect(formatInstantParam(Date.parse("2026-10-14T08:00:00.987Z"))).toBe("2026-10-14T08:00:00Z");
    const search = withReplayParams("?rack=R1", { tMs: T0, bMs: T0 + HOUR, hours: 24 });
    const back = parseReplayUrl(search);
    expect(back).toEqual({ tMs: T0, bMs: T0 + HOUR, hours: 24 });
    expect(new URLSearchParams(search).get("rack")).toBe("R1");
  });
  it("removes the parameters for live and omits the default window", () => {
    expect(withReplayParams("?t=2026-10-14T08:00:00Z&tb=2026-10-14T09:00:00Z&w=24", { tMs: null, bMs: null, hours: 6 })).toBe("");
    expect(withReplayParams("", { tMs: T0, bMs: null, hours: 6 })).toBe("?t=2026-10-14T00%3A00%3A00Z");
  });
  it("falls back to the default window for a bad ?w=", () => {
    expect(parseReplayUrl("?w=abc").hours).toBe(6);
    expect(parseReplayUrl("?w=500").hours).toBe(6);
    expect(parseReplayUrl("?w=1.5").hours).toBe(6);
    expect(parseReplayUrl("?w=72").hours).toBe(72);
  });
});

describe("looking a value up at a time", () => {
  const items = [sample(T0, 100), sample(T0 + 5 * MIN, 110), sample(T0 + 10 * MIN, 120)];
  it("holds the sample at or before the time, with its own timestamp and age, and never interpolates", () => {
    const s = seriesOf(items);
    const r = readAt(s, T0 + 7 * MIN);
    expect(r.kind).toBe("value");
    if (r.kind === "value") {
      expect(r.value).toBe(110);
      expect(r.atMs).toBe(T0 + 5 * MIN);
      expect(r.ageMs).toBe(2 * MIN);
      expect(r.stale).toBe(false);
    }
    const exact = readAt(s, T0 + 10 * MIN);
    expect(exact.kind === "value" && exact.value).toBe(120);
  });
  it("says before-start, no-data, and stale where it should", () => {
    const s = seriesOf(items);
    expect(readAt(s, T0 - MIN)).toEqual({ kind: "before-start", firstMs: T0 });
    expect(readAt(seriesOf([]), T0).kind).toBe("no-data");
    const late = readAt(s, T0 + 10 * MIN + 11 * MIN); // sampling 300 s -> stale after 600 s
    expect(late.kind === "value" && late.stale).toBe(true);
    // no interval reported by the backend: no staleness judgement is invented
    const unknown = readAt(seriesOf(items, { samplingIntervalS: null }), T0 + 5 * HOUR);
    expect(unknown.kind === "value" && unknown.stale).toBe(false);
  });
  it("reports a backend gap instead of a value", () => {
    const gap: TelemetryGap = { start: iso(T0 + 10 * MIN), end: iso(T0 + 40 * MIN), duration_s: 1800 };
    const s = seriesOf([...items, sample(T0 + 40 * MIN, 130)], { gaps: [gap] });
    const inside = readAt(s, T0 + 20 * MIN);
    expect(inside).toEqual({ kind: "gap", fromMs: T0 + 10 * MIN, toMs: T0 + 40 * MIN, durationS: 1800 });
    expect(readAt(s, T0 + 41 * MIN).kind).toBe("value");
  });
  it("uses only quality=ok samples; invalid ones are counted, not shown", () => {
    const s = seriesOf([sample(T0, 100), sample(T0 + 5 * MIN, 999999, { quality: "invalid", invalid_reason: "out_of_range" }), sample(T0 + 10 * MIN, 120)]);
    expect(s.excluded).toBe(1);
    const r = readAt(s, T0 + 6 * MIN);
    expect(r.kind === "value" && r.value).toBe(100);
  });
  it("counts an out-of-order page and still looks up correctly", () => {
    const s = seriesOf([sample(T0 + 10 * MIN, 120), sample(T0, 100), sample(T0 + 5 * MIN, 110)]);
    expect(s.orderViolations).toBeGreaterThan(0);
    const r = readAt(s, T0 + 6 * MIN);
    expect(r.kind === "value" && r.value).toBe(110);
  });
  it("skips samples whose time cannot be read, and counts them", () => {
    const s = seriesOf([sample(T0, 100), { ...sample(T0, 5), ts_event: "not a time" }]);
    expect(s.unreadable).toBe(1);
    expect(s.times).toHaveLength(1);
  });
  it("lists the distinct origins of the stored samples, and a missing origin as null", () => {
    const s = seriesOf([sample(T0, 1), sample(T0 + MIN, 2, { origin: "replay" }), sample(T0 + 2 * MIN, 3, { origin: null }), sample(T0 + 3 * MIN, 4)]);
    expect(s.origins).toEqual(["simulated", "replay", null]);
  });
  it("binary search helper", () => {
    expect(lastAtOrBefore([1, 3, 5], 0)).toBe(-1);
    expect(lastAtOrBefore([1, 3, 5], 4)).toBe(1);
    expect(lastAtOrBefore([1, 3, 5], 5)).toBe(2);
    expect(lastAtOrBefore([], 5)).toBe(-1);
  });
  it("staleAfterFor uses twice the interval or the backend threshold, whichever is larger", () => {
    expect(staleAfterFor(300, null)).toBe(600_000);
    expect(staleAfterFor(300, 900)).toBe(900_000);
    expect(staleAfterFor(null, null)).toBeNull();
  });
  it("span and emptiness", () => {
    expect(hasAnyData(dsOf(seriesOf([])))).toBe(false);
    expect(datasetSpan(dsOf(seriesOf(items)))).toEqual({ fromMs: T0, toMs: T0 + 10 * MIN });
    expect(datasetSpan(dsOf())).toBeNull();
  });
});

describe("compare mode (B minus A)", () => {
  const gap: TelemetryGap = { start: iso(T0 + 10 * MIN), end: iso(T0 + 40 * MIN), duration_s: 1800 };
  const s = seriesOf([sample(T0, 100), sample(T0 + 5 * MIN, 150), sample(T0 + 10 * MIN, 0), sample(T0 + 40 * MIN, 10)], { gaps: [gap] });
  const ds = dsOf(s);
  it("computes the delta and percent change", () => {
    const rows = compareSnapshots(ds, snapshotAt(ds, T0), snapshotAt(ds, T0 + 5 * MIN));
    const r = rows[0];
    expect(r.status).toBe("ok");
    if (r.status === "ok") {
      expect(r.a).toBe(100);
      expect(r.b).toBe(150);
      expect(r.delta).toBe(50);
      expect(r.pct).toBe(50);
    }
  });
  it("gives no percent when A is zero", () => {
    const rows = compareSnapshots(ds, snapshotAt(ds, T0 + 10 * MIN), snapshotAt(ds, T0 + 41 * MIN));
    const r = rows[0];
    expect(r.status === "ok" && r.pct).toBeNull();
    expect(r.status === "ok" && r.delta).toBe(10);
  });
  it("marks a side with no value as unavailable and names it", () => {
    const rowsB = compareSnapshots(ds, snapshotAt(ds, T0), snapshotAt(ds, T0 + 20 * MIN));
    expect(rowsB[0].status === "unavailable" && rowsB[0].missing).toBe("b");
    const rowsA = compareSnapshots(ds, snapshotAt(ds, T0 - MIN), snapshotAt(ds, T0));
    expect(rowsA[0].status === "unavailable" && rowsA[0].missing).toBe("a");
    const both = compareSnapshots(ds, snapshotAt(ds, T0 - MIN), snapshotAt(ds, T0 + 20 * MIN));
    expect(both[0].status === "unavailable" && both[0].missing).toBe("both");
  });
});

const alert = (id: number, ms: number | null, severity = "WARNING"): AlertRecord => ({
  id,
  created_at: ms === null ? null : iso(ms),
  type: "anomaly",
  message: `alert ${id}`,
  severity,
  score: 1,
  alert: true,
  acknowledged: false,
  acknowledged_by: null,
  acknowledged_at: null,
});

describe("alert pins", () => {
  it("keeps alerts inside the window, positions them, sorts by time and uses non-colour shapes", () => {
    const { pins, skipped, oldestMs } = alertPins([alert(3, T0 + 30 * MIN, "CRITICAL"), alert(2, T0 + 15 * MIN, "WARNING"), alert(1, T0 - HOUR, "INFO"), alert(4, null)], T0, T0 + HOUR);
    expect(pins.map((p) => p.id)).toEqual([2, 3]);
    expect(pins[0].fraction).toBe(0.25);
    expect(pins.map((p) => p.shape)).toEqual(["diamond", "triangle"]);
    expect(skipped).toBe(1);
    expect(oldestMs).toBe(T0 - HOUR);
  });
  it("flags a possibly incomplete pin list only when the fetch limit was reached before the window start", () => {
    expect(pinsMayBeIncomplete(200, T0 + MIN, T0)).toBe(true);
    expect(pinsMayBeIncomplete(200, T0 - MIN, T0)).toBe(false);
    expect(pinsMayBeIncomplete(10, T0 + MIN, T0)).toBe(false);
    expect(pinsMayBeIncomplete(200, null, T0)).toBe(false);
  });
  it("finds the next and previous pin strictly after/before a time", () => {
    const { pins } = alertPins([alert(1, T0 + 10 * MIN), alert(2, T0 + 20 * MIN)], T0, T0 + HOUR);
    expect(neighbourPin(pins, T0 + 10 * MIN, 1)?.id).toBe(2);
    expect(neighbourPin(pins, T0 + 10 * MIN, -1)).toBeNull();
    expect(neighbourPin(pins, T0 + 30 * MIN, -1)?.id).toBe(2);
    expect(neighbourPin(pins, T0 + 20 * MIN, 1)).toBeNull();
  });
});

describe("loading a replay window (pagination stitching)", () => {
  const window = { from: iso(T0), to: iso(T0 + HOUR) };
  const page = (items: TelemetrySample[], next: string | null, id: string): TelemetrySamplesPage => ({ external_id: id, unit: "kW", sampling_interval_s: 300, stream: "live", quality: "any", items, next_cursor: next });
  const noGaps = async (id: string) => ({ external_id: id, stream: "live", sampling_interval_s: 300, threshold_s: null, gaps: [] as TelemetryGap[], truncated: false });

  it("follows next_cursor, stitches pages in order and keeps every sample", async () => {
    const calls: (string | null | undefined)[] = [];
    const fetchers = {
      samples: async (id: string, p: { cursor?: string | null }) => {
        calls.push(p.cursor);
        return p.cursor == null ? page([sample(T0, 1), sample(T0 + 5 * MIN, 2)], "c1", id) : page([sample(T0 + 10 * MIN, 3)], null, id);
      },
      gaps: async (id: string) => noGaps(id),
    };
    const out = await loadReplay(1, window, undefined, fetchers as never);
    expect(out.failed).toEqual([]);
    expect(out.dataset.series).toHaveLength(MEASURANDS.length);
    const s = out.dataset.series[0];
    expect(s.values).toEqual([1, 2, 3]);
    expect(s.times).toEqual([T0, T0 + 5 * MIN, T0 + 10 * MIN]);
    expect(calls.filter((c) => c == null)).toHaveLength(MEASURANDS.length);
    expect(calls.filter((c) => c === "c1")).toHaveLength(MEASURANDS.length);
    expect(out.pagesLoaded).toBe(2 * MEASURANDS.length);
  });

  it("flags that more data exists when the page cap is hit (never silently truncates)", async () => {
    const fetchers = {
      samples: async (id: string) => page([sample(T0, 1)], "more", id),
      gaps: async (id: string) => noGaps(id),
    };
    const out = await loadReplay(1, window, undefined, fetchers as never);
    expect(out.dataset.series[0].moreAvailable).toBe(true);
  });

  it("carries backend gaps through to the lookup", async () => {
    const gap: TelemetryGap = { start: iso(T0 + 5 * MIN), end: iso(T0 + 30 * MIN), duration_s: 1500 };
    const fetchers = {
      samples: async (id: string) => page([sample(T0, 1), sample(T0 + 5 * MIN, 2), sample(T0 + 30 * MIN, 3)], null, id),
      gaps: async (id: string) => ({ ...(await noGaps(id)), gaps: [gap] }),
    };
    const out = await loadReplay(1, window, undefined, fetchers as never);
    expect(readAt(out.dataset.series[0], T0 + 12 * MIN).kind).toBe("gap");
  });

  it("an empty window loads as an empty dataset", async () => {
    const fetchers = { samples: async (id: string) => page([], null, id), gaps: async (id: string) => noGaps(id) };
    const out = await loadReplay(1, window, undefined, fetchers as never);
    expect(hasAnyData(out.dataset)).toBe(false);
    expect(out.failed).toEqual([]);
  });

  it("one failing measurand is named and the others still replay; all failing is an error", async () => {
    const some = {
      samples: async (id: string) => {
        if (id.endsWith("humidity_pct")) throw new Error("boom");
        return page([sample(T0, 1)], null, id);
      },
      gaps: async (id: string) => noGaps(id),
    };
    const out = await loadReplay(1, window, undefined, some as never);
    expect(out.failed).toEqual(["humidity_pct"]);
    expect(out.dataset.series).toHaveLength(MEASURANDS.length - 1);
    const none = { samples: async () => Promise.reject(new Error("down")), gaps: async (id: string) => noGaps(id) };
    let thrown = false;
    try {
      await loadReplay(1, window, undefined, none as never);
    } catch {
      thrown = true;
    }
    expect(thrown).toBe(true);
  });
});

describe("chart geometry", () => {
  const gap: TelemetryGap = { start: iso(T0 + 10 * MIN), end: iso(T0 + 40 * MIN), duration_s: 1800 };
  const s = seriesOf([sample(T0, 100), sample(T0 + 5 * MIN, 200), sample(T0 + 10 * MIN, 150), sample(T0 + 40 * MIN, 120), sample(T0 + 45 * MIN, 110)], { gaps: [gap] });
  const box = { width: 600, height: 100, fromMs: T0, toMs: T0 + HOUR };
  it("domain covers the data, never invents a range for a flat line, and is null with no data", () => {
    expect(valueDomain(s)).toEqual({ min: 100, max: 200 });
    expect(valueDomain(seriesOf([sample(T0, 5), sample(T0 + MIN, 5)]))).toEqual({ min: 4, max: 6 });
    expect(valueDomain(seriesOf([]))).toBeNull();
  });
  it("breaks the line at a backend gap instead of joining across it", () => {
    const d = buildPath(s, box, { min: 100, max: 200 });
    expect(d.split("M")).toHaveLength(3); // two segments
    expect(d.startsWith("M0,100")).toBe(true);
  });
  it("draws a single sample as a segment a person can see, and nothing for no data", () => {
    expect(buildPath(seriesOf([sample(T0, 1)]), box, { min: 0, max: 2 })).toContain("M0,50");
    expect(buildPath(seriesOf([]), box, { min: 0, max: 1 })).toBe("");
  });
  it("drops samples outside the window", () => {
    const d = buildPath(s, { ...box, fromMs: T0 + 6 * MIN, toMs: T0 + HOUR }, { min: 100, max: 200 });
    expect(d.split("M")).toHaveLength(3);
    expect(d).not.toContain("NaN");
  });
});
