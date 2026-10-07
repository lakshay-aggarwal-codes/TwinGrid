import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ getToken: vi.fn(async () => "tok1"), forceRefresh: vi.fn(async () => "tok2") }));
vi.mock("../authClient", () => {
  class AuthRequiredError extends Error {}
  return { AuthRequiredError, getToken: auth.getToken, forceRefresh: auth.forceRefresh };
});
vi.mock("../config", () => ({ API_BASE_URL: "https://api.example.com", assertApiConfigured: () => {} }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { AuthRequiredError } from "../authClient";
import { ApiError } from "./apiError";
import { ASSETS_PAGE_SIZE, fetchFacilityTopology } from "./facility";
import { FRAME_NOTE, seedAssets } from "@/three/facilityFixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const FACILITY = { id: 1, name: "Default Facility", frame_unit: "m", frame_note: FRAME_NOTE, created_at: "2026-10-02T00:00:00Z" };
const page = (assets: unknown[]) => ({ facility_id: 1, frame_unit: "m", as_of: "2026-10-06T00:00:00Z", count: assets.length, assets });

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
});

describe("fetchFacilityTopology", () => {
  it("fetches /api/facility then /api/assets with the bearer token; live topology only (no as_of, no include_unplaced)", async () => {
    const f = vi.fn(async (url: string) => (url.includes("/api/facility") ? json(FACILITY) : json(page(seedAssets()))));
    const raw = await fetchFacilityTopology(undefined, f as unknown as typeof fetch);
    expect(raw.facility.frame_unit).toBe("m");
    expect(raw.assets).toHaveLength(39);
    const urls = f.mock.calls.map((c) => c[0] as string);
    expect(urls[0]).toBe("https://api.example.com/api/facility");
    expect(urls[1]).toBe(`https://api.example.com/api/assets?limit=${ASSETS_PAGE_SIZE}&offset=0`);
    expect(urls.join(" ")).not.toMatch(/as_of|include_unplaced/);
    expect(((f.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer tok1");
  });

  it("paginates with limit <= 1000 until a short page", async () => {
    const full = Array.from({ length: ASSETS_PAGE_SIZE }, (_, i) => ({ ...seedAssets()[3], id: i + 1, external_id: `a${i}` }));
    const f = vi.fn(async (url: string) => {
      if (url.includes("/api/facility")) return json(FACILITY);
      return url.includes("offset=0") ? json(page(full)) : json(page(seedAssets().slice(0, 5)));
    });
    const raw = await fetchFacilityTopology(undefined, f as unknown as typeof fetch);
    expect(raw.assets).toHaveLength(ASSETS_PAGE_SIZE + 5);
    expect(f.mock.calls.map((c) => c[0] as string).filter((u) => u.includes("/api/assets"))).toHaveLength(2);
    expect(ASSETS_PAGE_SIZE).toBeLessThanOrEqual(1000);
  });

  it.each([
    [404, "not_found"],
    [403, "forbidden"],
    [429, "rate_limited"],
    [503, "unavailable"],
    [500, "server"],
  ] as const)("HTTP %s -> ApiError %s", async (status, kind) => {
    const f = vi.fn(async () => json({ detail: "secret" }, status));
    const err = (await fetchFacilityTopology(undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe(kind);
    expect(err.message).not.toMatch(/secret/);
  });

  it("a response that fails the contract is kind 'contract', not partial data", async () => {
    const f = vi.fn(async (url: string) => (url.includes("/api/facility") ? json(FACILITY) : json({ facility_id: 1, assets: "nope" })));
    const err = (await fetchFacilityTopology(undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe("contract");
  });

  it("a non-JSON 2xx is a server error", async () => {
    const f = vi.fn(async () => new Response("<html>", { status: 200 }));
    const err = (await fetchFacilityTopology(undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe("server");
  });

  it("401 refreshes once; a second 401 is AuthRequiredError", async () => {
    const f = vi.fn().mockResolvedValueOnce(json({}, 401)).mockResolvedValueOnce(json(FACILITY)).mockResolvedValueOnce(json(page(seedAssets())));
    await fetchFacilityTopology(undefined, f as unknown as typeof fetch);
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    const g = vi.fn(async () => json({}, 401));
    await expect(fetchFacilityTopology(undefined, g as unknown as typeof fetch)).rejects.toBeInstanceOf(AuthRequiredError);
  });

  it("a network failure is kind 'network'", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = (await fetchFacilityTopology(undefined, f as unknown as typeof fetch).catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe("network");
  });
});
