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
import { ESG_REPORT_FILENAME, esgErrorKind, fetchEsgReportPdf } from "./esgReport.ts";

const pdf = (status = 200, type = "application/pdf") =>
  new Response(status === 200 ? new Blob(["%PDF-1.4 x"]) : "backend says: <b>secret detail</b>", { status, headers: { "Content-Type": type } });

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
  auth.getToken.mockImplementation(async () => "tok1");
  auth.forceRefresh.mockImplementation(async () => "tok2");
});

describe("fetchEsgReportPdf", () => {
  it("fetches /api/esg_report with the bearer token and returns the PDF blob unchanged", async () => {
    const f = vi.fn(async () => pdf());
    const file = await fetchEsgReportPdf(undefined, f as unknown as typeof fetch);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/esg_report");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
    expect(file.filename).toBe(ESG_REPORT_FILENAME);
    expect(file.blob.type).toBe("application/pdf");
    expect(await file.blob.text()).toBe("%PDF-1.4 x");
  });

  it("on 401 refreshes once and retries once with the new token", async () => {
    const f = vi.fn().mockResolvedValueOnce(pdf(401, "application/json")).mockResolvedValueOnce(pdf());
    const file = await fetchEsgReportPdf(undefined, f as unknown as typeof fetch);
    expect(f).toHaveBeenCalledTimes(2);
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect(((f.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer tok2");
    expect(file.blob.size).toBeGreaterThan(0);
  });

  it("a second 401 is an AuthRequiredError (sign in again), not a loop", async () => {
    const f = vi.fn(async () => pdf(401, "application/json"));
    await expect(fetchEsgReportPdf(undefined, f as unknown as typeof fetch)).rejects.toBeInstanceOf(AuthRequiredError);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
    [429, "rate_limited"],
    [503, "unavailable"],
    [500, "server"],
    [502, "server"],
    [400, "validation"],
  ] as const)("HTTP %s maps to ApiError kind %s, with client-chosen text only", async (status, kind) => {
    const f = vi.fn(async () => pdf(status, "text/html"));
    const err = await fetchEsgReportPdf(undefined, f as unknown as typeof fetch).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe(kind);
    expect((err as ApiError).message).not.toMatch(/secret|backend says|<b>/);
    expect(esgErrorKind(status)).toBe(kind);
  });

  it("a 2xx that is not a PDF (e.g. an HTML page) is a server error, never a download", async () => {
    const f = vi.fn(async () => new Response("<html>login</html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    const err = await fetchEsgReportPdf(undefined, f as unknown as typeof fetch).catch((e: unknown) => e);
    expect((err as ApiError).kind).toBe("server");
  });

  it("a network failure is kind 'network'; an abort passes through", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = await fetchEsgReportPdf(undefined, down as unknown as typeof fetch).catch((e: unknown) => e);
    expect((err as ApiError).kind).toBe("network");
    const abort = vi.fn(async () => {
      throw Object.assign(new Error("x"), { name: "AbortError" });
    });
    const e2 = await fetchEsgReportPdf(undefined, abort as unknown as typeof fetch).catch((e: unknown) => e);
    expect((e2 as Error).name).toBe("AbortError");
  });

  it("no session: AuthRequiredError from the token step is not swallowed", async () => {
    auth.getToken.mockImplementationOnce(async () => {
      throw new AuthRequiredError();
    });
    await expect(fetchEsgReportPdf(undefined, vi.fn() as unknown as typeof fetch)).rejects.toBeInstanceOf(AuthRequiredError);
  });
});
