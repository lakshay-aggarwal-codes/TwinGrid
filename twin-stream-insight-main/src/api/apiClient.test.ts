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

import { ApiError, fetchAlerts, fetchOptimized, fetchState, fetchWhatIf } from "./apiClient";
import { validAlert, validState } from "./testFixtures";

const res = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  ({
    ok: status < 400,
    status,
    statusText: "s",
    headers: { get: (k: string) => headers[k] ?? null },
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  }) as unknown as Response;

beforeEach(() => {
  getToken.mockReset().mockResolvedValue("tok-1");
  forceRefresh.mockReset().mockResolvedValue("tok-2");
  reportError.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("authedFetch (via fetchAlerts)", () => {
  it("sends the bearer token", async () => {
    const f = vi.fn().mockResolvedValue(res(200, []));
    vi.stubGlobal("fetch", f);
    await fetchAlerts();
    expect(f.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-1");
    expect(forceRefresh).not.toHaveBeenCalled();
  });

  it("on 401 refreshes once and retries with the new token", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(res(401, { detail: "Invalid or expired token" }))
      .mockResolvedValueOnce(res(200, [validAlert()]));
    vi.stubGlobal("fetch", f);
    await expect(fetchAlerts()).resolves.toHaveLength(1);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
    expect(f.mock.calls[1][1].headers.Authorization).toBe("Bearer tok-2");
  });

  it("does not loop: a second 401 becomes AuthRequiredError after one retry", async () => {
    const f = vi.fn().mockResolvedValue(res(401, { detail: "nope" }));
    vi.stubGlobal("fetch", f);
    await expect(fetchAlerts()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(f).toHaveBeenCalledTimes(2);
    expect(forceRefresh).toHaveBeenCalledTimes(1);
  });

  it("propagates AuthRequiredError when the session is gone", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(401, {})));
    forceRefresh.mockRejectedValue(new AuthRequiredError());
    await expect(fetchAlerts()).rejects.toBeInstanceOf(AuthRequiredError);
  });

  it("propagates AuthRequiredError from getToken without calling fetch", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    getToken.mockRejectedValue(new AuthRequiredError());
    await expect(fetchAlerts()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(f).not.toHaveBeenCalled();
  });

  it("does not treat 403 as an auth failure (viewer calling an operator route)", async () => {
    const f = vi.fn().mockResolvedValue(res(403, { detail: "Operator role required" }));
    vi.stubGlobal("fetch", f);
    await expect(fetchOptimized()).rejects.toMatchObject({ kind: "forbidden", status: 403 });
    expect(forceRefresh).not.toHaveBeenCalled();
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("retries a POST only after a 401, never after a network failure", async () => {
    const f = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", f);
    await expect(fetchOptimized()).rejects.toMatchObject({ kind: "network" });
    expect(f).toHaveBeenCalledTimes(1);
    expect(forceRefresh).not.toHaveBeenCalled();
  });

  it("passes the AbortSignal through and rethrows an abort untouched", async () => {
    const controller = new AbortController();
    const abort = Object.assign(new Error("aborted"), { name: "AbortError" });
    const f = vi.fn().mockRejectedValue(abort);
    vi.stubGlobal("fetch", f);
    const p = fetchWhatIf(
      { utilisation: 0.5, outside_temp: 20, water_stress: 0, mode: "auto", chilled_water_temp: 7 },
      controller.signal
    );
    await expect(p).rejects.toBe(abort);
    expect(f.mock.calls[0][1].signal).toBe(controller.signal);
  });
});

describe("typed errors", () => {
  it.each([
    [400, "validation"],
    [404, "not_found"],
    [409, "conflict"],
    [422, "validation"],
    [429, "rate_limited"],
    [500, "server"],
    [502, "unavailable"],
    [503, "unavailable"],
  ])("maps HTTP %i to kind %s", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(status, { detail: "x" })));
    await expect(fetchAlerts()).rejects.toMatchObject({ kind, status });
  });

  it("never puts backend detail text in safeMessage or message; the raw detail goes only to reportError", async () => {
    const secret = "SELECT * FROM users -- internal detail";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(500, { detail: secret })));
    const err = await fetchAlerts().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.safeMessage).not.toContain("SELECT");
    expect(err.message).toBe(err.safeMessage);
    expect(reportError).toHaveBeenCalledWith("apiClient.http", expect.stringContaining(secret), "error");
  });

  it("reads Retry-After and a machine code from the body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(429, { code: "rate_limited", detail: "slow down" }, { "Retry-After": "7" })));
    await expect(fetchAlerts()).rejects.toMatchObject({ kind: "rate_limited", code: "rate_limited", retryAfterS: 7 });
  });

  it("reads the machine code from the problem+json `type` urn (backend api/errors.py)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(503, { type: "urn:twingrid:error:model_unavailable", status: 503, detail: "model_unavailable" })));
    await expect(fetchOptimized()).rejects.toMatchObject({ kind: "unavailable", status: 503, code: "model_unavailable" });
  });

  it("ignores a code that does not look like an identifier", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(400, { code: "<script>alert(1)</script>" })));
    const err = await fetchAlerts().catch((e) => e);
    expect(err.code).toBeUndefined();
  });

  it("maps an HTML 502 body to 'unavailable' with no raw text", async () => {
    const html = "<html><body><h1>502 Bad Gateway</h1>nginx</body></html>";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(502, html)));
    const err = await fetchAlerts().catch((e) => e);
    expect(err).toMatchObject({ kind: "unavailable", status: 502 });
    expect(err.message).not.toMatch(/nginx|html|Bad Gateway/i);
    expect(err.safeMessage).not.toMatch(/nginx|html|Bad Gateway/i);
  });

  it("treats a non-JSON 200 body as a server error, not a thrown raw string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, "<html>captive portal</html>")));
    const err = await fetchAlerts().catch((e) => e);
    expect(err).toMatchObject({ kind: "server", status: 200 });
    expect(err.message).not.toContain("captive");
  });
});

describe("contract validation and adapters", () => {
  it("rejects a payload that breaks the contract as kind 'contract' (no defaults substituted)", async () => {
    const { pue, ...missingPue } = validState();
    void pue;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, missingPue)));
    await expect(fetchState()).rejects.toMatchObject({ kind: "contract" });
    expect(reportError).toHaveBeenCalledWith("contract.GET /api/state", expect.anything());
  });

  it("rejects a string where a number is required (no coercion)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, validState({ pue: "1.2" }))));
    await expect(fetchState()).rejects.toMatchObject({ kind: "contract" });
  });

  it("returns a valid state and keeps an unrecognised cooling_mode as its raw string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, validState({ cooling_mode: "liquid_immersion" }))));
    const s = await fetchState();
    expect(s.cooling_mode).toBe("liquid_immersion");
    expect(s.pue).toBe(1.2);
  });

  it("keeps alert severity vocabulary verbatim, known or unknown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(res(200, [validAlert({ severity: "CRITICAL" }), validAlert({ id: 2, severity: "FATAL" })]))
    );
    const rows = await fetchAlerts();
    expect(rows.map((r) => r.severity)).toEqual(["CRITICAL", "FATAL"]);
  });

  it("does not turn a missing optional field into a value", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(200, validState())));
    const s = await fetchState();
    expect("water_stress" in s).toBe(false);
    expect("carbon_data_is_real" in s).toBe(false);
  });
});
