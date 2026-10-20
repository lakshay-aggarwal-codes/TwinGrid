import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
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
import { accessPage, accessRequest } from "./accessFixtures";
import { decideAccessRequest, fetchAccessRequest, fetchAccessRequests, resendAccessActivation, resendAccessNotification } from "./api";
import { useAccessActions } from "./useAccessRequests";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const asFetch = (f: unknown) => f as typeof fetch;
const call = (f: ReturnType<typeof vi.fn>, i = 0) => f.mock.calls[i] as unknown as [string, RequestInit];

beforeEach(() => vi.clearAllMocks());

describe("access-request API calls", () => {
  it("lists with the bearer token and the query string", async () => {
    const f = vi.fn(async () => json(200, accessPage()));
    const page = await fetchAccessRequests("status=pending&limit=20", undefined, asFetch(f));
    expect(page.items).toHaveLength(1);
    const [url, init] = call(f);
    expect(url).toBe("https://api.example.com/api/admin/access-requests?status=pending&limit=20");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
  });

  it("reads one request, encoding the id", async () => {
    const f = vi.fn(async () => json(200, accessRequest({ decision_note: "n" })));
    expect((await fetchAccessRequest("a/b c", undefined, asFetch(f))).decision_note).toBe("n");
    expect(call(f)[0]).toBe("https://api.example.com/api/admin/access-requests/a%2Fb%20c");
  });

  it("approve and reject POST the note (or an empty object) to the right path and parse the returned row", async () => {
    const f = vi.fn(async () => json(200, accessRequest({ status: "approved" })));
    expect((await decideAccessRequest("id1", "approve", "ok", asFetch(f))).status).toBe("approved");
    let [url, init] = call(f);
    expect(url).toBe("https://api.example.com/api/admin/access-requests/id1/approve");
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"note":"ok"}');
    await decideAccessRequest("id1", "reject", null, asFetch(f));
    [url, init] = call(f, 1);
    expect(url).toBe("https://api.example.com/api/admin/access-requests/id1/reject");
    expect(init.body).toBe("{}");
  });

  it("a malformed body is a contract error, not repaired", async () => {
    const f = vi.fn(async () => json(200, { items: [{ id: "x" }], next_before_id: null }));
    await expect(fetchAccessRequests("limit=20", undefined, asFetch(f))).rejects.toMatchObject({ kind: "contract" });
  });

  it("409 becomes a conflict ApiError without the server's text", async () => {
    const f = vi.fn(async () => json(409, { error: "invalid_transition", detail: "SECRET DETAIL" }));
    const err = await decideAccessRequest("id1", "approve", null, asFetch(f)).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ kind: "conflict", status: 409 });
    expect(String((err as Error).message)).not.toContain("SECRET");
  });

  it("the resend calls POST with no body and do not need a response body", async () => {
    const f = vi.fn(async () => new Response(null, { status: 204 }));
    await expect(resendAccessNotification("id1", asFetch(f))).resolves.toBeUndefined();
    await expect(resendAccessActivation("id1", asFetch(f))).resolves.toBeUndefined();
    expect(call(f, 0)[0]).toBe("https://api.example.com/api/admin/access-requests/id1/resend-notification");
    expect(call(f, 1)[0]).toBe("https://api.example.com/api/admin/access-requests/id1/resend-activation");
    expect(call(f, 0)[1].body).toBeUndefined();
  });

  it("retries once with a fresh token on 401", async () => {
    const f = vi.fn().mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(200, accessPage()));
    await fetchAccessRequests("limit=20", undefined, asFetch(f));
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    expect((call(f, 1)[1].headers as Record<string, string>).Authorization).toBe("Bearer tok2");
  });
});

describe("useAccessActions refetches after a write", () => {
  const setup = () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    return { spy, ...renderHook(() => useAccessActions(), { wrapper }) };
  };
  const keys = (spy: ReturnType<typeof vi.spyOn>) => spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey: unknown }).queryKey));

  it("on success: the queue and the audit log are refetched", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, accessRequest({ status: "approved" }))));
    const { result, spy } = setup();
    await act(async () => void (await result.current.decide("id1", "approve", null)));
    expect(keys(spy)).toEqual(['["admin-access"]', '["admin-audit"]']);
    vi.unstubAllGlobals();
  });

  it("on a 409 it refetches the queue and still throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(409, { error: "invalid_transition" })));
    const { result, spy } = setup();
    await act(async () => {
      await expect(result.current.decide("id1", "approve", null)).rejects.toMatchObject({ kind: "conflict" });
    });
    expect(keys(spy)).toContain('["admin-access"]');
    vi.unstubAllGlobals();
  });

  it("on a server error it does not refetch", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(500, {})));
    const { result, spy } = setup();
    await act(async () => {
      await expect(result.current.resendActivation("id1")).rejects.toMatchObject({ kind: "server" });
    });
    expect(spy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
