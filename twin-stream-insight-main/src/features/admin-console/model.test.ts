import { describe, expect, it } from "vitest";
import {
  EMPTY_AUDIT_FORM,
  MAX_FILTER_CHARS,
  MAX_URL_CHARS,
  auditQuery,
  canSetRole,
  checkHealthy,
  checkWord,
  componentHealthy,
  componentWord,
  deliveryText,
  describeDetails,
  docsHref,
  parseWebhookUrl,
  timeText,
  uptimeText,
  webhookLabel,
} from "./model";

describe("canSetRole (UX hint; the server decides)", () => {
  it("is true for someone else and a different, known role", () => {
    expect(canSetRole({ is_you: false, role: "viewer" }, "operator")).toBe(true);
    expect(canSetRole({ is_you: false, role: "admin" }, "viewer")).toBe(true);
  });
  it("is false for yourself, for no change and for a role that does not exist", () => {
    expect(canSetRole({ is_you: true, role: "admin" }, "viewer")).toBe(false);
    expect(canSetRole({ is_you: false, role: "viewer" }, "viewer")).toBe(false);
    expect(canSetRole({ is_you: false, role: "viewer" }, "root")).toBe(false);
  });
});

describe("auditQuery", () => {
  it("leaves empty fields out and trims the rest", () => {
    expect(auditQuery(EMPTY_AUDIT_FORM)).toEqual({ ok: true, value: "" });
    const r = auditQuery({ ...EMPTY_AUDIT_FORM, action: " login_failure ", username: "  ", outcome: "denied" }, { limit: 50 });
    expect(r).toEqual({ ok: true, value: "action=login_failure&outcome=denied&limit=50" });
  });
  it("adds the paging cursor only when there is one", () => {
    expect(auditQuery(EMPTY_AUDIT_FORM, { limit: 50, beforeId: 8 })).toEqual({ ok: true, value: "limit=50&before_id=8" });
    expect(auditQuery(EMPTY_AUDIT_FORM, { limit: 50, beforeId: null })).toEqual({ ok: true, value: "limit=50" });
  });
  it("sends times as UTC instants", () => {
    const r = auditQuery({ ...EMPTY_AUDIT_FORM, since: "2026-01-01T12:00", until: "2026-01-02T12:00" });
    expect(r.ok).toBe(true);
    if (r.ok) {
      const q = new URLSearchParams(r.value);
      expect(q.get("since")).toBe(new Date("2026-01-01T12:00").toISOString());
      expect(q.get("until")).toBe(new Date("2026-01-02T12:00").toISOString());
    }
  });
  it("refuses a bad date, an inverted range and an over-long value, and says which", () => {
    expect(auditQuery({ ...EMPTY_AUDIT_FORM, since: "not a date" })).toEqual({ ok: false, error: "From: enter a valid date and time." });
    expect(auditQuery({ ...EMPTY_AUDIT_FORM, until: "garbage" })).toEqual({ ok: false, error: "To: enter a valid date and time." });
    expect(auditQuery({ ...EMPTY_AUDIT_FORM, since: "2026-02-01T00:00", until: "2026-01-01T00:00" })).toEqual({ ok: false, error: "From is after To." });
    expect(auditQuery({ ...EMPTY_AUDIT_FORM, username: "x".repeat(MAX_FILTER_CHARS + 1) })).toEqual({ ok: false, error: `User is longer than ${MAX_FILTER_CHARS} characters.` });
    expect(auditQuery({ ...EMPTY_AUDIT_FORM, username: "x".repeat(MAX_FILTER_CHARS) }).ok).toBe(true);
  });
  it("encodes a hostile value as data", () => {
    const r = auditQuery({ ...EMPTY_AUDIT_FORM, username: "a&before_id=1#" });
    expect(r).toEqual({ ok: true, value: "username=a%26before_id%3D1%23" });
  });
});

describe("text helpers", () => {
  it("shows UTC times plainly, and anything else as it came", () => {
    expect(timeText("2026-01-01T12:00:00+00:00")).toBe("2026-01-01 12:00:00 UTC");
    expect(timeText("2026-01-01T12:00:00.123456+00:00")).toBe("2026-01-01 12:00:00 UTC");
    expect(timeText("2026-01-01T12:00:00+05:30")).toBe("2026-01-01T12:00:00+05:30");
    expect(timeText(null)).toBe("unknown");
  });
  it("summarises details as plain text, truncated", () => {
    expect(describeDetails(null)).toBe("");
    expect(describeDetails({ reason: "bad", n: 3, nested: { a: 1 } })).toBe('reason: bad, n: 3, nested: {"a":1}');
    const long = describeDetails({ blob: "x".repeat(500) }, 40);
    expect(long.length).toBe(40);
    expect(long.endsWith("…")).toBe(true);
  });
  it("describes uptime", () => {
    expect(uptimeText(5)).toBe("5 s");
    expect(uptimeText(600)).toBe("10 min");
    expect(uptimeText(7500)).toBe("2 h 5 min");
    expect(uptimeText(200_000)).toBe("2 d 7 h");
  });
});

describe("webhooks", () => {
  it("is named by scheme, host and port only", () => {
    expect(webhookLabel({ scheme: "https", host: "hooks.example.com", port: null })).toBe("https://hooks.example.com");
    expect(webhookLabel({ scheme: "https", host: "h.example.com", port: 8443 })).toBe("https://h.example.com:8443");
  });
  it("words a delivery, and a failure by its kind (never an unknown kind as success)", () => {
    expect(deliveryText({ ok: true, status_code: 200, error_kind: null, duration_ms: 42 })).toBe("Delivered (HTTP 200) in 42 ms");
    expect(deliveryText({ ok: false, status_code: 500, error_kind: "http_error", duration_ms: 1 })).toBe("Failed: the endpoint returned an error (HTTP 500)");
    expect(deliveryText({ ok: false, status_code: null, error_kind: "timeout", duration_ms: 5000 })).toBe("Failed: timed out");
    expect(deliveryText({ ok: false, status_code: null, error_kind: "blocked_url", duration_ms: 0 })).toContain("not https or not a public address");
    expect(deliveryText({ ok: false, status_code: null, error_kind: "something_new", duration_ms: 0 })).toBe("Failed: unknown error");
    expect(deliveryText({ ok: false, status_code: null, error_kind: null, duration_ms: 0 })).toBe("Failed: unknown error");
  });
  it("checks a URL only for emptiness and length (the server enforces the rest)", () => {
    expect(parseWebhookUrl("  https://a.example.com/x  ")).toEqual({ ok: true, value: "https://a.example.com/x" });
    expect(parseWebhookUrl("   ").ok).toBe(false);
    expect(parseWebhookUrl("h".repeat(MAX_URL_CHARS + 1)).ok).toBe(false);
    expect(parseWebhookUrl("h".repeat(MAX_URL_CHARS)).ok).toBe(true);
  });
});

describe("system status wording", () => {
  it("only ok and skipped are healthy; a word this client does not know is not", () => {
    expect(checkHealthy("ok")).toBe(true);
    expect(checkHealthy("skipped")).toBe(true);
    for (const v of ["fail", "behind", "missing", "stale", "gave_up", "not_running", "unknown", "brand_new"]) expect(checkHealthy(v)).toBe(false);
    expect(checkWord("gave_up")).toBe("Gave up");
    expect(checkWord("brand_new")).toBe("brand_new");
  });
  it("words components", () => {
    expect(componentHealthy("loaded")).toBe(true);
    expect(componentHealthy("not_configured")).toBe(true);
    expect(componentHealthy("degraded")).toBe(false);
    expect(componentHealthy("not_loaded")).toBe(false);
    expect(componentWord("not_loaded")).toBe("Not loaded");
  });
  it("builds a docs link from the API base, and falls back to the path", () => {
    expect(docsHref("https://api.example.com", "/docs")).toBe("https://api.example.com/docs");
    expect(docsHref("", "/docs")).toBe("/docs");
    expect(docsHref("not a base", "/docs")).toBe("/docs");
  });
});
