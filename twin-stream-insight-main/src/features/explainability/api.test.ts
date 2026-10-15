import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  AuthRequiredError: class AuthRequiredError extends Error {},
  getToken: vi.fn(async () => "tok1"),
  forceRefresh: vi.fn(async () => "tok2"),
}));
vi.mock("@/authClient", () => ({ AuthRequiredError: auth.AuthRequiredError, getToken: auth.getToken, forceRefresh: auth.forceRefresh }));
vi.mock("@/config", () => ({ API_BASE_URL: "https://api.example.com", assertApiConfigured: () => {} }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import { explanationPath, fetchExplanation, fetchPassport, passportPath } from "./api";
import passportJson from "./fixtures/passport.json";
import explanationJson from "./fixtures/explanation.json";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const asFetch = (f: unknown) => f as unknown as typeof fetch;
const kindOf = async (p: Promise<unknown>) => {
  try {
    await p;
  } catch (e) {
    return e instanceof ApiError ? e.kind : "not-api-error";
  }
  return "no-error";
};

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
});

describe("paths", () => {
  it("are fixed or built from a numeric id only", () => {
    expect(passportPath()).toBe("/api/models/passport");
    expect(explanationPath(7)).toBe("/api/alerts/7/explanation");
  });
});

describe("fetchPassport / fetchExplanation", () => {
  it("GET with the bearer token and parse the real body", async () => {
    const f = vi.fn(async () => json(200, passportJson));
    const p = await fetchPassport(undefined, asFetch(f));
    expect(p.models.length).toBe(8);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/models/passport");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");

    const g = vi.fn(async () => json(200, explanationJson));
    expect((await fetchExplanation(7, undefined, asFetch(g))).alert_id).toBe(7);
    expect((g.mock.calls[0] as unknown as [string])[0]).toBe("https://api.example.com/api/alerts/7/explanation");
  });

  it("a body that does not match is a contract error, never repaired", async () => {
    expect(await kindOf(fetchPassport(undefined, asFetch(vi.fn(async () => json(200, { models: [] })))))).toBe("contract");
    expect(await kindOf(fetchExplanation(7, undefined, asFetch(vi.fn(async () => json(200, { alert_id: 7 })))))).toBe("contract");
  });

  it("maps statuses to error kinds without reading the body text", async () => {
    const cases: [number, string][] = [[403, "forbidden"], [404, "not_found"], [429, "rate_limited"], [503, "unavailable"], [500, "server"]];
    for (const [status, kind] of cases) {
      expect(await kindOf(fetchPassport(undefined, asFetch(vi.fn(async () => json(status, { detail: "/secret/path Traceback" })))))).toBe(kind);
    }
  });

  it("a network failure is kind network", async () => {
    expect(await kindOf(fetchPassport(undefined, asFetch(vi.fn(async () => Promise.reject(new TypeError("boom"))))))).toBe("network");
  });

  it("refreshes once on 401 and retries once; a second 401 is an auth error", async () => {
    const f = vi.fn().mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(200, passportJson));
    await fetchPassport(undefined, asFetch(f));
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect(((f.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer tok2");
    const g = vi.fn(async () => json(401, {}));
    await expect(fetchPassport(undefined, asFetch(g))).rejects.toBeInstanceOf(auth.AuthRequiredError);
    expect(g).toHaveBeenCalledTimes(2);
  });
});
