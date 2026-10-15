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
import { fetchInbox, fetchTimeline, inboxPath, patchAlert, patchPath, timelinePath } from "./api";
import { alertRow } from "./testFixtures";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const asFetch = (f: unknown) => f as unknown as typeof fetch;

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
});

describe("paths are built from numeric ids only", () => {
  it("builds the three endpoints", () => {
    expect(inboxPath()).toBe("/api/alerts/inbox?limit=200");
    expect(timelinePath(7)).toBe("/api/alerts/7/events");
    expect(patchPath(7)).toBe("/api/alerts/7");
  });
});

describe("fetchInbox", () => {
  it("GETs with the bearer token and parses the rows", async () => {
    const f = vi.fn(async () => json(200, [alertRow({ id: 3 })]));
    const rows = await fetchInbox(undefined, asFetch(f));
    expect(rows.map((r) => r.id)).toEqual([3]);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/alerts/inbox?limit=200");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
  });

  it("a body that does not match the schema is a contract error, never repaired", async () => {
    const f = vi.fn(async () => json(200, [{ id: 1, message: "no status field" }]));
    await expect(fetchInbox(undefined, asFetch(f))).rejects.toMatchObject({ kind: "contract" });
  });

  it("a status outside the lifecycle is a contract error", async () => {
    const f = vi.fn(async () => json(200, [{ ...alertRow(), status: "closed" }]));
    await expect(fetchInbox(undefined, asFetch(f))).rejects.toMatchObject({ kind: "contract" });
  });

  it("maps statuses to error kinds and keeps Retry-After", async () => {
    const cases: [number, string][] = [[403, "forbidden"], [404, "not_found"], [429, "rate_limited"], [503, "unavailable"], [500, "server"]];
    for (const [status, kind] of cases) {
      const f = vi.fn(async () => json(status, { detail: "secret backend text" }, status === 429 ? { "Retry-After": "7" } : {}));
      const err = (await fetchInbox(undefined, asFetch(f)).catch((e: unknown) => e)) as ApiError;
      expect(err).toBeInstanceOf(ApiError);
      expect(err.kind).toBe(kind);
      expect(err.message).not.toContain("secret backend text");
      if (status === 429) expect(err.retryAfterS).toBe(7);
    }
  });

  it("a network failure is a network error", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    await expect(fetchInbox(undefined, asFetch(f))).rejects.toMatchObject({ kind: "network" });
  });

  it("refreshes once on 401 and retries with the new token; a second 401 ends the session", async () => {
    const ok = vi.fn().mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(200, []));
    await expect(fetchInbox(undefined, asFetch(ok))).resolves.toEqual([]);
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect(((ok.mock.calls[1] as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization).toBe("Bearer tok2");

    const dead = vi.fn(async () => json(401, {}));
    await expect(fetchInbox(undefined, asFetch(dead))).rejects.toBeInstanceOf(auth.AuthRequiredError);
  });
});

describe("fetchTimeline", () => {
  it("parses entries", async () => {
    const f = vi.fn(async () => json(200, { alert_id: 1, entries: [{ at: "2026-10-01T08:00:00+00:00", kind: "created", actor: null, summary: "Alert raised by the detector", note: null }] }));
    const t = await fetchTimeline(1, undefined, asFetch(f));
    expect(t.entries[0].summary).toBe("Alert raised by the detector");
  });
});

describe("patchAlert", () => {
  it("PATCHes a JSON body with the bearer token and resolves to the server's row", async () => {
    const f = vi.fn(async () => json(200, alertRow({ id: 9, status: "acknowledged", acknowledged: true, acknowledged_by: "op1" })));
    const row = await patchAlert(9, { status: "acknowledged" }, undefined, asFetch(f));
    expect(row).toMatchObject({ id: 9, status: "acknowledged", acknowledged_by: "op1" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/alerts/9");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ status: "acknowledged" });
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok1");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("sends null to clear an assignee", async () => {
    const f = vi.fn(async () => json(200, alertRow()));
    await patchAlert(1, { assignee: null }, undefined, asFetch(f));
    expect(JSON.parse((f.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ assignee: null });
  });

  it("409 is a conflict, 422 is validation", async () => {
    await expect(patchAlert(1, { status: "open" }, undefined, asFetch(vi.fn(async () => json(409, {}))))).rejects.toMatchObject({ kind: "conflict" });
    await expect(patchAlert(1, { assignee: "x" }, undefined, asFetch(vi.fn(async () => json(422, {}))))).rejects.toMatchObject({ kind: "validation" });
  });
});
