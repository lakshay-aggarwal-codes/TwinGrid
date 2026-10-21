import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  AuthRequiredError: class AuthRequiredError extends Error {},
  getToken: vi.fn(async () => "tok1"),
  forceRefresh: vi.fn(async () => "tok2"),
}));
const report = vi.hoisted(() => ({ reportError: vi.fn() }));
vi.mock("@/authClient", () => ({ AuthRequiredError: auth.AuthRequiredError, getToken: auth.getToken, forceRefresh: auth.forceRefresh }));
vi.mock("@/config", () => ({ API_BASE_URL: "https://api.example.com", assertApiConfigured: () => {} }));
vi.mock("@/lib/errorReporter", () => report);

import { ApiError } from "@/api/apiError";
import { askCopilot } from "./api";
import { RULE_BASED } from "./testFixtures";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const asFetch = (f: unknown) => f as unknown as typeof fetch;
const BODY = { question: "Secret question text", context: { kind: "alert" as const, id: "42" }, history: [] };

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
  report.reportError.mockClear();
});

describe("askCopilot", () => {
  it("POSTs the body with the bearer token and parses the answer", async () => {
    const f = vi.fn(async () => json(200, RULE_BASED));
    const r = await askCopilot(BODY, undefined, asFetch(f));
    expect(r.mode).toBe("rule_based");
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/copilot/ask");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
    expect(JSON.parse(String(init.body))).toEqual(BODY);
  });

  it("refreshes once on 401 and replays", async () => {
    const f = vi.fn().mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(200, RULE_BASED));
    await askCopilot(BODY, undefined, asFetch(f));
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect((f.mock.calls[1][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok2" });
  });

  it("a second 401 asks the user to sign in again", async () => {
    const f = vi.fn(async () => json(401, {}));
    await expect(askCopilot(BODY, undefined, asFetch(f))).rejects.toBeInstanceOf(auth.AuthRequiredError);
  });

  it("maps statuses to kinds and keeps Retry-After", async () => {
    const cases: [number, string][] = [[404, "not_found"], [422, "validation"], [429, "rate_limited"], [503, "unavailable"], [500, "server"]];
    for (const [status, kind] of cases) {
      const f = vi.fn(async () => json(status, { error: "secret backend text" }, status === 429 ? { "Retry-After": "30" } : {}));
      const err = (await askCopilot(BODY, undefined, asFetch(f)).catch((e: unknown) => e)) as ApiError;
      expect(err).toBeInstanceOf(ApiError);
      expect(err.kind).toBe(kind);
      expect(err.message).not.toMatch(/secret/);
      if (status === 429) expect(err.retryAfterS).toBe(30);
    }
  });

  it("a body that does not match the contract is a contract error, never repaired", async () => {
    const bad = { ...RULE_BASED, evidence: [{ ...RULE_BASED.evidence[0], origin: "live" }] };
    await expect(askCopilot(BODY, undefined, asFetch(vi.fn(async () => json(200, bad))))).rejects.toMatchObject({ kind: "contract" });
    await expect(askCopilot(BODY, undefined, asFetch(vi.fn(async () => json(200, { answer: "x" }))))).rejects.toMatchObject({ kind: "contract" });
  });

  it("a network failure is kind network and nothing reported contains the question", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("offline");
    });
    await expect(askCopilot(BODY, undefined, asFetch(f))).rejects.toMatchObject({ kind: "network" });
    expect(JSON.stringify(report.reportError.mock.calls)).not.toMatch(/Secret question/);
  });

  it("an abort is passed through, not turned into a network error", async () => {
    const f = vi.fn(async () => {
      throw Object.assign(new Error("aborted"), { name: "AbortError" });
    });
    await expect(askCopilot(BODY, undefined, asFetch(f))).rejects.toMatchObject({ name: "AbortError" });
  });
});
