import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  getToken: vi.fn(async () => "tok1"),
  forceRefresh: vi.fn(async () => "tok2"),
}));

vi.mock("../authClient", () => {
  class AuthRequiredError extends Error {}
  return { AuthRequiredError, getToken: auth.getToken, forceRefresh: auth.forceRefresh };
});
vi.mock("../config", () => ({ API_BASE_URL: "https://api.example.com", assertApiConfigured: () => {} }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { AuthRequiredError } from "../authClient";
import { ApiError } from "./apiError";
import { acknowledgePath, acknowledgeAlert, alertsQueryKey } from "./alerts";

const res = (status: number, headers: Record<string, string> = {}, body = "{}") => new Response(body, { status, headers });

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
});

describe("acknowledgeAlert", () => {
  it("POSTs /api/alerts/{id}/acknowledge with the bearer token and resolves on 2xx", async () => {
    const f = vi.fn(async () => res(200, {}, '{"anything":"ignored"}'));
    await expect(acknowledgeAlert(42, undefined, f as unknown as typeof fetch)).resolves.toBeUndefined();
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/alerts/42/acknowledge");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
  });

  it("builds the path from a numeric id only", () => {
    expect(acknowledgePath(7)).toBe("/api/alerts/7/acknowledge");
    expect(alertsQueryKey(50)).toEqual(["alerts", 50]);
  });

  it("on 401 refreshes once and retries once", async () => {
    const f = vi.fn().mockResolvedValueOnce(res(401)).mockResolvedValueOnce(res(204));
    await acknowledgeAlert(1, undefined, f as unknown as typeof fetch);
    expect(f).toHaveBeenCalledTimes(2);
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect(((f.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer tok2");
  });

  it("a second 401 is AuthRequiredError", async () => {
    const f = vi.fn(async () => res(401));
    await expect(acknowledgeAlert(1, undefined, f as unknown as typeof fetch)).rejects.toBeInstanceOf(AuthRequiredError);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [429, "rate_limited"],
    [503, "unavailable"],
    [500, "server"],
  ] as const)("HTTP %s -> ApiError kind %s; backend body never becomes the message", async (status, kind) => {
    const f = vi.fn(async () => res(status, {}, '{"detail":"secret internal detail"}'));
    const err = await acknowledgeAlert(1, undefined, f as unknown as typeof fetch).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe(kind);
    expect((err as ApiError).status).toBe(status);
    expect((err as ApiError).message).not.toMatch(/secret/);
    // Non-401 failures are never retried (a POST is not replayed).
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("429 keeps Retry-After", async () => {
    const f = vi.fn(async () => res(429, { "Retry-After": "12" }));
    const err = (await acknowledgeAlert(1, undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err.retryAfterS).toBe(12);
  });

  it("a network failure is kind 'network' and is not retried", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = (await acknowledgeAlert(1, undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe("network");
    expect(f).toHaveBeenCalledTimes(1);
  });
});
