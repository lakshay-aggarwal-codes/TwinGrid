import { describe, expect, it } from "vitest";
import type { FreshnessState } from "@/telemetry/freshness";
import { computeThermalColors, WAITING_COLOR } from "./thermalMapping";
import { currentState, feedProvenance, getModeColor, noDataNotice, toReadout } from "./visualizationModes";
import { feedIn } from "./feedTestUtils";

const STATES: FreshnessState[] = ["connecting", "live", "stale", "disconnected", "reconnecting", "unavailable"];

describe("toReadout: the rendering mode for numbers (roadmap section 8)", () => {
  it.each([
    ["live", "current"],
    ["stale", "last-known"],
    ["disconnected", "last-known"],
    ["reconnecting", "last-known"],
    ["unavailable", "none"],
    ["connecting", "none"],
  ] as const)("%s -> %s", (state, mode) => {
    expect(toReadout(feedIn(state)).mode).toBe(mode);
  });

  it("'last known' always carries its age, and never exists without a frame or an age", () => {
    for (const s of ["stale", "disconnected", "reconnecting"] as const) {
      const r = toReadout(feedIn(s, { ageMs: 42_000 }));
      expect(r.mode).toBe("last-known");
      if (r.mode === "last-known") expect(r.ageMs).toBe(42_000);
      expect(toReadout(feedIn(s, { ageMs: null })).mode).toBe("none");
      expect(toReadout(feedIn(s, { withFrame: false })).mode).toBe("none");
    }
  });

  it("a live freshness without a frame has no numbers; an absent feed is 'connecting'", () => {
    expect(toReadout(feedIn("live", { withFrame: false })).mode).toBe("none");
    expect(toReadout(undefined)).toEqual({ mode: "none", freshness: "connecting" });
    expect(toReadout(null)).toEqual({ mode: "none", freshness: "connecting" });
  });

  it("only `current` may use the live style: exactly the live state yields it", () => {
    for (const s of STATES) expect(toReadout(feedIn(s)).mode === "current").toBe(s === "live");
  });
});

describe("scene tint: stale / disconnected -> neutral", () => {
  const NEUTRAL_BASE = getModeColor("energy", null).base;

  it("currentState is the frame only while live", () => {
    expect(currentState(feedIn("live"))?.pue).toBe(1.23);
    for (const s of ["stale", "disconnected", "reconnecting", "unavailable", "connecting"] as const) {
      expect(currentState(feedIn(s))).toBeNull();
    }
  });

  it("thermal: live tints from the reading; every other state yields no colours (WAITING_COLOR on every rack)", () => {
    const cur = currentState(feedIn("live", { state: { server_inlet_temp_C: 26, server_outlet_temp_C: 44 } }));
    expect(cur).not.toBeNull();
    expect(computeThermalColors(cur && { inletTempC: cur.server_inlet_temp_C, outletTempC: cur.server_outlet_temp_C })).not.toBeNull();
    for (const s of ["stale", "disconnected", "reconnecting", "unavailable", "connecting"] as const) {
      const cs = currentState(feedIn(s, { state: { server_inlet_temp_C: 26, server_outlet_temp_C: 44 } }));
      expect(cs).toBeNull();
      expect(computeThermalColors(cs ? { inletTempC: cs.server_inlet_temp_C, outletTempC: cs.server_outlet_temp_C } : null)).toBeNull();
    }
    expect(WAITING_COLOR).toBe("#3d4045");
  });

  it.each(["energy", "cooling", "sustainability"] as const)("%s: a stale or disconnected frame gets the neutral colour, a live frame does not", (mode) => {
    const live = getModeColor(mode, currentState(feedIn("live", { state: { pue: 2.4, wue: 3.1, cooling_mode: "free_air" } })));
    expect(live.base).not.toBe(NEUTRAL_BASE);
    for (const s of ["stale", "disconnected", "reconnecting"] as const) {
      expect(getModeColor(mode, currentState(feedIn(s, { state: { pue: 2.4, wue: 3.1, cooling_mode: "free_air" } })))).toEqual(getModeColor(mode, null));
    }
  });
});

describe("noDataNotice", () => {
  it.each([
    ["connecting", "loading"],
    ["unavailable", "unavailable"],
    ["disconnected", "disconnected"],
    ["reconnecting", "disconnected"],
    ["stale", "stale"],
  ] as const)("%s -> %s notice with text, never a bare number", (state, kind) => {
    const n = noDataNotice(state);
    expect(n.kind).toBe(kind);
    expect(n.text.length).toBeGreaterThan(3);
    expect(n.text).not.toBe("0");
  });
});

describe("feedProvenance", () => {
  it("builds a live-feed view from the stamped frame: origin, server time, simulated clock, freshness", () => {
    const v = feedProvenance(feedIn("stale", { ageMs: 42_000 }));
    expect(v.kind).toBe("live-feed");
    expect(v.origin.state).toBe("simulated");
    expect(v.strip.line).toBe("Live feed · server time 14:03:21 UTC · simulated clock 2026-01-01 12:35");
    expect(v.freshness?.text).toBe("Stale · last update 42 s ago");
  });

  it("absent origin is Unverified source; the feed can never be 'measured' unless the frame says so", () => {
    expect(feedProvenance(feedIn("live", { origin: null })).origin.state).toBe("unverified");
    expect(feedProvenance(feedIn("live", { origin: "simulated" })).origin.state).toBe("simulated");
    expect(feedProvenance(feedIn("live", { origin: "measured" })).origin.state).toBe("measured");
  });

  it("flags the flat carbon fallback only when the backend says carbon_data_is_real === false", () => {
    const ids = (c?: boolean) => feedProvenance(feedIn("live", { state: { carbon_data_is_real: c } })).flags.map((f) => f.text);
    expect(ids(false)).toContain("Fallback carbon (flat constant)");
    expect(ids(true)).toEqual([]);
    expect(ids(undefined)).toEqual([]);
  });

  it("with no frame it still reports freshness (chip only) and passes the reconnect attempt through", () => {
    const f = { ...feedIn("reconnecting", { withFrame: false, attempt: 3 }) };
    expect(feedProvenance(f).freshness?.text).toBe("Reconnecting (attempt 3)");
  });
});
