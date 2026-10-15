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
import { createProposal, decideProposal, fetchProposals, fetchRecommendation, fetchSandbox, fetchShadowSummary, postShadowSample } from "./api";
import { proposalBody, type Context } from "./model";
import { EFFECT, RECOMMENDATION, proposal } from "./testFixtures";

const CTX: Context = { utilisation: 0.65, outside_temp: 22, water_stress: 0.1, mode: "auto", chilled_water_temp: 10, inlet_temp_c: null };
const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const asFetch = (f: unknown) => f as unknown as typeof fetch;
const problem = (status: number, code: string) => json(status, { type: `urn:twingrid:error:${code}`, detail: "secret backend text" });

beforeEach(() => {
  auth.getToken.mockClear();
  auth.forceRefresh.mockClear();
});

describe("reads", () => {
  it("fetchRecommendation sends the context as query parameters and parses the response", async () => {
    const f = vi.fn(async () => json(200, RECOMMENDATION));
    const r = await fetchRecommendation(CTX, undefined, asFetch(f));
    expect(r.recommendation.selected?.name).toBe("pid");
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    const u = new URL(url);
    expect(u.pathname).toBe("/api/optimizer/baseline-recommendation");
    expect(u.searchParams.get("current_chilled_water_temp")).toBe("10");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok1");
  });

  it("fetchSandbox passes the proposed set-points", async () => {
    const f = vi.fn(async () => json(200, { predicted: EFFECT, persisted: false }));
    await fetchSandbox(CTX, { chilled_water_temp_c: 9, cooling_mode: "free_air" }, undefined, asFetch(f));
    const u = new URL((f.mock.calls[0] as unknown as [string])[0]);
    expect(u.pathname).toBe("/api/optimizer/sandbox");
    expect(u.searchParams.get("proposed_mode")).toBe("free_air");
  });

  it("a response that is not what the contract says is a contract error", async () => {
    const f = vi.fn(async () => json(200, { recommendation: { selected: null }, persisted: true }));
    await expect(fetchRecommendation(CTX, undefined, asFetch(f))).rejects.toMatchObject({ kind: "contract" });
    const bad = vi.fn(async () => json(200, [{ ...proposal(), status: "maybe" }]));
    await expect(fetchProposals(undefined, asFetch(bad))).rejects.toMatchObject({ kind: "contract" });
  });

  it("parses the shadow summary", async () => {
    const f = vi.fn(async () => json(200, { n_samples: 4, agreement_rate: 0.5 }));
    expect(await fetchShadowSummary(undefined, asFetch(f))).toMatchObject({ n_samples: 4, agreement_rate: 0.5 });
  });
});

describe("the 503 'optimizer not available' state", () => {
  it("is kind unavailable with the machine code kept and the backend text dropped", async () => {
    const f = vi.fn(async () => problem(503, "model_unavailable"));
    const err = (await postShadowSample(undefined, asFetch(f)).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("unavailable");
    expect(err.code).toBe("model_unavailable");
    expect(err.message).not.toContain("secret backend text");
  });
});

describe("writes", () => {
  it("createProposal POSTs the body and resolves to the server's row", async () => {
    const f = vi.fn(async () => json(201, proposal({ id: 7 })));
    const body = proposalBody(CTX, { chilled_water_temp_c: 11, cooling_mode: "hybrid" }, "why");
    const row = await createProposal(body, undefined, asFetch(f));
    expect(row.id).toBe(7);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/api/optimizer/proposals");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toMatchObject({ chilled_water_temp_c: 11, cooling_mode: "hybrid", rationale: "why" });
  });

  it("decideProposal sends the decision and a trimmed note only when there is one", async () => {
    const f = vi.fn(async () => json(200, proposal({ status: "approved", decided_by: "admin1" })));
    await decideProposal(3, "approve", "  ok  ", undefined, asFetch(f));
    await decideProposal(3, "reject", "   ", undefined, asFetch(f));
    const bodies = f.mock.calls.map((c) => JSON.parse((c as unknown as [string, RequestInit])[1].body as string));
    expect(bodies).toEqual([{ decision: "approve", note: "ok" }, { decision: "reject" }]);
    expect(new URL((f.mock.calls[0] as unknown as [string])[0]).pathname).toBe("/api/optimizer/proposals/3/decision");
  });

  it("keeps the machine code of a refusal: self_decision (403), not_pending (409), unsafe_prediction (422)", async () => {
    const cases: [number, string, string][] = [[403, "self_decision", "forbidden"], [409, "not_pending", "conflict"], [422, "unsafe_prediction", "validation"]];
    for (const [status, code, kind] of cases) {
      const f = vi.fn(async () => problem(status, code));
      const err = (await decideProposal(1, "approve", "", undefined, asFetch(f)).catch((e: unknown) => e)) as ApiError;
      expect([err.kind, err.code]).toEqual([kind, code]);
    }
  });

  it("refreshes once on 401 and retries; a second 401 ends the session", async () => {
    const ok = vi.fn().mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(200, proposal()));
    await expect(decideProposal(1, "reject", "", undefined, asFetch(ok))).resolves.toMatchObject({ id: 1 });
    expect(auth.forceRefresh).toHaveBeenCalledTimes(1);
    const dead = vi.fn(async () => json(401, {}));
    await expect(decideProposal(1, "reject", "", undefined, asFetch(dead))).rejects.toBeInstanceOf(auth.AuthRequiredError);
  });
});
