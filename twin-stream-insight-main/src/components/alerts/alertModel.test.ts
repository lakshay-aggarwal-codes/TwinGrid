import { describe, expect, it } from "vitest";
import { alertProvenance, alertTime, attributionEvidence, groupByEpisode, lifecycleOf, scoreLabel, severityView } from "./alertModel";
import { alertRow } from "./alertFixtures";

describe("severityView", () => {
  it.each([
    ["INFO", "info"],
    ["WARNING", "warning"],
    ["CRITICAL", "critical"],
  ])("%s is known, with its own icon shape and its own text", (sev, icon) => {
    expect(severityView(sev)).toEqual({ text: sev, icon, known: true });
  });

  it.each(["SEVERE", "critical", "Warning", "", "  "])("unknown severity %j is neutral and keeps the raw text", (sev) => {
    const v = severityView(sev);
    expect(v.known).toBe(false);
    expect(v.icon).toBe("unknown");
    expect(v.text).toBe(sev.trim() === "" ? "not reported" : sev.trim());
  });

  it("non-string severity is 'not reported', never invented", () => {
    expect(severityView(null)).toMatchObject({ text: "not reported", known: false });
    expect(severityView(undefined)).toMatchObject({ text: "not reported", known: false });
  });

  it("each known severity has a distinct icon shape", () => {
    const icons = ["INFO", "WARNING", "CRITICAL", "x"].map((s) => severityView(s).icon);
    expect(new Set(icons).size).toBe(4);
  });
});

describe("alertTime", () => {
  it("an offset-less (naive) time is shown as UTC and labelled '(UTC assumed)'", () => {
    expect(alertTime("2026-10-06T10:00:00")).toEqual({ text: "2026-10-06 10:00:00 UTC (UTC assumed)", assumed: true, reported: true });
  });

  it("a time with an offset is converted to UTC and is NOT labelled assumed", () => {
    expect(alertTime("2026-10-06T12:00:00+02:00")).toEqual({ text: "2026-10-06 10:00:00 UTC", assumed: false, reported: true });
    expect(alertTime("2026-10-06T10:00:00Z")).toMatchObject({ text: "2026-10-06 10:00:00 UTC", assumed: false });
  });

  it.each([null, undefined, ""])("%j is 'not reported'", (v) => {
    expect(alertTime(v)).toEqual({ text: "not reported", assumed: false, reported: false });
  });

  it("an unreadable time is stated as such, never rendered raw or as a wrong date", () => {
    expect(alertTime("yesterday")).toEqual({ text: "not reported (unreadable)", assumed: false, reported: false });
    expect(alertTime("2026-02-30T00:00:00")).toMatchObject({ reported: false });
  });
});

describe("score and lifecycle", () => {
  it("the score is a detector score (reconstruction error) with no percentage", () => {
    expect(scoreLabel(0.123456)).toBe("Detector score (reconstruction error): 0.1235");
    expect(scoreLabel(12)).not.toContain("%");
  });

  it("lifecycle is exactly new / acknowledged", () => {
    expect(lifecycleOf({ acknowledged: false })).toBe("new");
    expect(lifecycleOf({ acknowledged: true })).toBe("acknowledged");
  });
});

describe("groupByEpisode", () => {
  it("groups by dedupe_key, keeps EVERY row in original order, and groups sit where their first row is", () => {
    const rows = [
      alertRow({ id: 5, dedupe_key: "ep-a" }),
      alertRow({ id: 4, dedupe_key: null }),
      alertRow({ id: 3, dedupe_key: "ep-a" }),
      alertRow({ id: 2, dedupe_key: "ep-b" }),
      alertRow({ id: 1, dedupe_key: "ep-a" }),
    ];
    const groups = groupByEpisode(rows);
    expect(groups.map((g) => [g.key, g.rows.map((r) => r.id)])).toEqual([
      ["ep-a", [5, 3, 1]],
      [null, [4]],
      ["ep-b", [2]],
    ]);
    expect(groups.flatMap((g) => g.rows.map((r) => r.id)).sort()).toEqual([1, 2, 3, 4, 5]);
  });

  it("rows without a key (or an empty key) are never merged with each other", () => {
    const groups = groupByEpisode([alertRow({ id: 1 }), alertRow({ id: 2 }), alertRow({ id: 3, dedupe_key: "" })]);
    expect(groups).toHaveLength(3);
    expect(groups.every((g) => g.key === null && g.rows.length === 1)).toBe(true);
  });

  it("an empty list is an empty grouping", () => {
    expect(groupByEpisode([])).toEqual([]);
  });
});

describe("provenance and evidence", () => {
  it("absent origin is Unverified source; recognised origins are shown; never Measured unless the backend says so", () => {
    expect(alertProvenance(alertRow({ id: 1, origin: undefined })).origin.state).toBe("unverified");
    expect(alertProvenance(alertRow({ id: 1, origin: null })).origin.state).toBe("unverified");
    expect(alertProvenance(alertRow({ id: 1, origin: "simulated" })).origin.state).toBe("simulated");
    expect(alertProvenance(alertRow({ id: 1, origin: "weird" })).origin.state).toBe("unverified");
  });

  it("attribution fields are returned verbatim only when the backend sent them", () => {
    expect(attributionEvidence(alertRow({ id: 1 }))).toEqual([]);
    const r = { ...alertRow({ id: 1 }), sensor_reading_id: 77, trigger: "threshold", context: { a: 1 } } as never;
    expect(attributionEvidence(r)).toEqual([
      { field: "sensor_reading_id", value: "77" },
      { field: "trigger", value: "threshold" },
      { field: "context", value: '{"a":1}' },
    ]);
    expect(attributionEvidence({ ...alertRow({ id: 1 }), sensor_reading_id: null } as never)).toEqual([]);
  });
});
