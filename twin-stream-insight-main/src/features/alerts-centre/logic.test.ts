import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ AuthRequiredError: class AuthRequiredError extends Error {} }));
// The error class lives in vi.hoisted: a class declared inside a vi.mock factory breaks module loading here.
vi.mock("@/authClient", () => ({ AuthRequiredError: auth.AuthRequiredError }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { runBulk } from "./bulk";
import { changeErrorText } from "./errors";
import {
  BULK_MAX,
  NO_FILTERS,
  applyFilters,
  bulkAckTargets,
  countAlerts,
  formatUtc,
  nextStatuses,
  parseAlertParam,
  parseInstantMs,
  replayHref,
  scanForNewCritical,
  selectableOpenIds,
  severityOf,
  toggleIn,
  toggleSelected,
  withAlertParam,
} from "./model";
import { readSoundPref, writeSoundPref } from "./prefs";
import { alertRow } from "./testFixtures";

const rows = [
  alertRow({ id: 5, severity: "CRITICAL", status: "open" }),
  alertRow({ id: 4, severity: "CRITICAL", status: "acknowledged", acknowledged: true }),
  alertRow({ id: 3, severity: "WARNING", status: "open" }),
  alertRow({ id: 2, severity: "INFO", status: "resolved" }),
  alertRow({ id: 1, severity: "WARNING", status: "open" }),
];

describe("lifecycle mirror", () => {
  it("offers exactly the moves the backend allows", () => {
    expect(nextStatuses("open")).toEqual(["acknowledged", "resolved"]);
    expect(nextStatuses("acknowledged")).toEqual(["open", "resolved"]);
    expect(nextStatuses("resolved")).toEqual(["open"]);
  });
  it("classifies severities and keeps an unknown one unknown", () => {
    expect(severityOf("CRITICAL")).toBe("CRITICAL");
    expect(severityOf("catastrophic")).toBe("UNKNOWN");
  });
});

describe("filters and counts", () => {
  it("no filter keeps everything; severity and status combine with AND, within a group OR", () => {
    expect(applyFilters(rows, NO_FILTERS)).toHaveLength(5);
    expect(applyFilters(rows, { severities: ["CRITICAL"], statuses: [] }).map((a) => a.id)).toEqual([5, 4]);
    expect(applyFilters(rows, { severities: ["CRITICAL", "WARNING"], statuses: ["open"] }).map((a) => a.id)).toEqual([5, 3, 1]);
    expect(applyFilters(rows, { severities: [], statuses: ["resolved"] }).map((a) => a.id)).toEqual([2]);
  });
  it("counts by status and counts only OPEN critical alerts as critical", () => {
    expect(countAlerts(rows)).toEqual({ total: 5, open: 3, acknowledged: 1, resolved: 1, openCritical: 1 });
  });
  it("toggleIn adds and removes without mutating", () => {
    const a: readonly string[] = ["x"];
    expect(toggleIn(a, "y")).toEqual(["x", "y"]);
    expect(toggleIn(["x", "y"], "x")).toEqual(["y"]);
    expect(a).toEqual(["x"]);
  });
});

describe("selection and bulk targets", () => {
  it("only open alerts are selectable, capped at BULK_MAX", () => {
    expect(selectableOpenIds(rows)).toEqual([5, 3, 1]);
    const many = Array.from({ length: BULK_MAX + 10 }, (_, i) => alertRow({ id: i + 1 }));
    expect(selectableOpenIds(many)).toHaveLength(BULK_MAX);
  });
  it("a bulk acknowledge skips selected alerts that are no longer open", () => {
    expect(bulkAckTargets(new Set([5, 4, 2, 99]), rows)).toEqual([5]);
  });
  it("toggleSelected returns a new set", () => {
    const s = new Set([1]);
    expect([...toggleSelected(s, 2)]).toEqual([1, 2]);
    expect([...toggleSelected(s, 1)]).toEqual([]);
    expect([...s]).toEqual([1]);
  });
});

describe("new critical alert detection", () => {
  it("the first scan remembers the backlog and announces nothing", () => {
    const first = scanForNewCritical(null, rows);
    expect(first.fresh).toEqual([]);
    expect([...first.seen].sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5]);
  });
  it("later scans announce a new OPEN critical alert exactly once", () => {
    const first = scanForNewCritical(null, rows);
    const fresh = alertRow({ id: 6, severity: "CRITICAL" });
    const second = scanForNewCritical(first.seen, [fresh, ...rows]);
    expect(second.fresh.map((a) => a.id)).toEqual([6]);
    expect(scanForNewCritical(second.seen, [fresh, ...rows]).fresh).toEqual([]);
  });
  it("ignores new warnings, new already-acknowledged criticals and re-listed old alerts", () => {
    const first = scanForNewCritical(null, rows);
    const next = [
      alertRow({ id: 7, severity: "WARNING" }),
      alertRow({ id: 8, severity: "CRITICAL", status: "acknowledged", acknowledged: true }),
      ...rows,
    ];
    expect(scanForNewCritical(first.seen, next).fresh).toEqual([]);
  });
});

describe("time and links", () => {
  it("reads an offset timestamp and a bare one (UTC) the same way", () => {
    expect(parseInstantMs("2026-10-01T08:00:00+00:00")).toBe(Date.UTC(2026, 9, 1, 8));
    expect(parseInstantMs("2026-10-01T08:00:00")).toBe(Date.UTC(2026, 9, 1, 8));
    expect(parseInstantMs("2026-10-01T10:00:00+02:00")).toBe(Date.UTC(2026, 9, 1, 8));
    expect(parseInstantMs(null)).toBeNull();
    expect(parseInstantMs("not a time")).toBeNull();
  });
  it("formats UTC and says so when there is no time", () => {
    expect(formatUtc("2026-10-01T08:00:00+00:00")).toBe("2026-10-01 08:00:00 UTC");
    expect(formatUtc(null)).toBe("time not reported");
  });
  it("builds the Replay link from the alert's own time, or none", () => {
    const href = replayHref("2026-10-01T08:00:00+00:00");
    expect(href).not.toBeNull();
    const url = new URL(href as string, "http://x");
    expect(url.pathname).toBe("/replay");
    expect(url.searchParams.get("t")).toBe("2026-10-01T08:00:00Z");
    expect(replayHref(null)).toBeNull();
  });
  it("?alert= accepts only a positive integer and round-trips", () => {
    expect(parseAlertParam("?alert=12")).toBe(12);
    for (const bad of ["?alert=0", "?alert=-1", "?alert=1.5", "?alert=abc", "?alert=", "", "?alert=12345678901"]) {
      expect(parseAlertParam(bad)).toBeNull();
    }
    expect(withAlertParam("?x=1", 9)).toBe("?x=1&alert=9");
    expect(withAlertParam("?alert=9", null)).toBe("");
  });
});

describe("bulk runner", () => {
  const conflict = () => new ApiError({ kind: "conflict", status: 409 });
  it("records a per-alert failure and carries on", async () => {
    const apply = vi.fn(async (id: number) => {
      if (id === 2) throw conflict();
    });
    const progress = vi.fn();
    const r = await runBulk([1, 2, 3], apply, progress);
    expect(r).toEqual({ done: [1, 3], failed: [{ id: 2, kind: "conflict" }], skipped: [] });
    expect(progress).toHaveBeenLastCalledWith(3, 3);
  });
  it("stops at a rate limit, a permission failure or a lost session and reports the rest as not attempted", async () => {
    for (const err of [new ApiError({ kind: "rate_limited", status: 429 }), new ApiError({ kind: "forbidden", status: 403 }), new AuthRequiredError()]) {
      const apply = vi.fn(async (id: number) => {
        if (id === 2) throw err;
      });
      const r = await runBulk([1, 2, 3, 4], apply);
      expect(r.done).toEqual([1]);
      expect(r.failed).toHaveLength(1);
      expect(r.skipped).toEqual([3, 4]);
      expect(apply).toHaveBeenCalledTimes(2);
    }
  });
  it("runs strictly one at a time", async () => {
    let active = 0;
    let peak = 0;
    await runBulk([1, 2, 3], async () => {
      active += 1;
      peak = Math.max(peak, active);
      await Promise.resolve();
      active -= 1;
    });
    expect(peak).toBe(1);
  });
});

describe("error text", () => {
  it("is chosen from the error kind and never contains backend text", () => {
    const e = new ApiError({ kind: "conflict", status: 409 });
    expect(changeErrorText(e)).toMatch(/no longer possible/);
    expect(changeErrorText(new ApiError({ kind: "forbidden", status: 403 }))).toBe("Only operators can change alerts.");
    expect(changeErrorText(new ApiError({ kind: "validation", status: 422 }))).toMatch(/existing operator/);
    expect(changeErrorText(new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 12 }))).toMatch(/12 seconds/);
    expect(changeErrorText(new AuthRequiredError())).toMatch(/Sign in again/);
    expect(changeErrorText(new Error("SELECT * FROM alerts"))).not.toMatch(/SELECT/);
  });
});

describe("sound preference", () => {
  const store = () => {
    const m = new Map<string, string>();
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
  };
  it("is OFF by default, turns on, and turns off again", () => {
    const s = store();
    expect(readSoundPref(s)).toBe(false);
    writeSoundPref(true, s);
    expect(readSoundPref(s)).toBe(true);
    writeSoundPref(false, s);
    expect(readSoundPref(s)).toBe(false);
  });
  it("a blocked store means off, not a crash", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readSoundPref(blocked)).toBe(false);
  });
});
