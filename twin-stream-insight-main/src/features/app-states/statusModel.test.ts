import { describe, expect, it } from "vitest";
import type { FreshnessState } from "@/telemetry/freshness";
import { connectionView, lastUpdateText, originChip } from "./statusModel";

const STATES: FreshnessState[] = ["connecting", "live", "stale", "disconnected", "reconnecting", "unavailable"];

describe("status bar model", () => {
  it("has wording and an icon for every freshness state, and only the outages are assertive", () => {
    for (const s of STATES) {
      const v = connectionView(s);
      expect(v.label.length).toBeGreaterThan(0);
      expect(v.assertive).toBe(s === "disconnected" || s === "unavailable");
    }
    expect(connectionView("unavailable").label).toBe("Backend unavailable");
  });

  it("says plainly when nothing has been received, and otherwise gives the age", () => {
    expect(lastUpdateText(null, 5000)).toBe("No data received yet");
    expect(lastUpdateText(1000, 5000)).toBe("Last update: 4 s ago");
    expect(lastUpdateText(1000, 125_000)).toBe("Last update: 2 min ago");
    expect(lastUpdateText(9000, 5000)).toBe("Last update: 0 s ago"); // clock never goes negative
  });

  it("claims nothing about the origin before a frame, and never promotes an unknown origin", () => {
    expect(originChip(false, "simulated")).toEqual({ state: null, text: "Data origin: not reported yet" });
    expect(originChip(true, "simulated")).toEqual({ state: "simulated", text: "Data origin: Simulated" });
    expect(originChip(true, undefined).state).toBe("unverified");
    expect(originChip(true, "Simulated").state).toBe("unverified"); // exact match only
    expect(originChip(true, "something-else").text).toBe("Data origin: Unverified source");
  });
});
