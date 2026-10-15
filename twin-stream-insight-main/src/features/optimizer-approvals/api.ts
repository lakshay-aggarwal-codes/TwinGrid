/**
 * Task 19: the optimizer page's requests. Same discipline as `features/alerts-centre/api.ts`: bearer token from the auth
 * client, one refresh-and-retry on 401, failures reduced to an `ApiError` kind (never body text), bodies parsed against
 * their schema (a mismatch is "contract", never repaired). `POST /api/optimize` is NOT here: the page reuses
 * `fetchOptimized` from the shared API client.
 */
import { z } from "zod";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import {
  ProposalListSchema,
  ProposalSchema,
  RecommendationSchema,
  SandboxSchema,
  ShadowSchema,
  recommendationQuery,
  sandboxQuery,
  type Context,
  type Proposal,
  type ProposalBody,
  type Recommendation,
  type Sandbox,
  type Setpoints,
  type ShadowSummary,
} from "./model";

const ShadowSampleSchema = z.object({}).passthrough();

export const recommendationKey = (q: Record<string, string>) => ["optimizer-recommendation", q] as const;
export const proposalsKey = ["optimizer-proposals"] as const;
export const shadowKey = ["optimizer-shadow"] as const;

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

/** The `urn:twingrid:error:<code>` machine code of a problem body, or undefined. The detail text is never read. */
async function problemCode(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.clone().json()) as { type?: unknown };
    const m = typeof body.type === "string" ? /^urn:twingrid:error:([a-z_]{1,40})$/.exec(body.type) : null;
    return m ? m[1] : undefined;
  } catch {
    return undefined;
  }
}

interface Call<S extends z.ZodTypeAny> {
  method: "GET" | "POST";
  path: string;
  query?: Record<string, string>;
  label: string;
  schema: S;
  body?: unknown;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

async function send(url: string, token: string, c: Call<z.ZodTypeAny>): Promise<Response> {
  try {
    return await (c.fetchImpl ?? fetch)(url, {
      method: c.method,
      signal: c.signal,
      headers: { Authorization: `Bearer ${token}`, ...(c.body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: c.body === undefined ? undefined : JSON.stringify(c.body),
    });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("optimizer-approvals.network", `Request to ${c.label} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

async function call<S extends z.ZodTypeAny>(c: Call<S>): Promise<z.output<S>> {
  assertApiConfigured();
  const url = new URL(c.path, API_BASE_URL);
  for (const [k, v] of Object.entries(c.query ?? {})) url.searchParams.set(k, v);
  const href = url.toString();
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("optimizer-approvals.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(href, token, c);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("optimizer-approvals.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(href, fresh, c);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("optimizer-approvals.http", `${response.status} ${c.label}`, response.status >= 500 ? "error" : "warning");
    const code = await problemCode(response);
    throw new ApiError({
      kind: kindFor(response.status),
      status: response.status,
      ...(code !== undefined && { code }),
      retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")),
    });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("optimizer-approvals.http", `${response.status} ${c.label}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(c.schema, body, c.label);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}

export const fetchRecommendation = (ctx: Context, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Recommendation> =>
  call({ method: "GET", path: "/api/optimizer/baseline-recommendation", query: recommendationQuery(ctx), label: "GET /api/optimizer/baseline-recommendation", schema: RecommendationSchema, signal, fetchImpl });

export const fetchSandbox = (ctx: Context, sp: Setpoints, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Sandbox> =>
  call({ method: "GET", path: "/api/optimizer/sandbox", query: sandboxQuery(ctx, sp), label: "GET /api/optimizer/sandbox", schema: SandboxSchema, signal, fetchImpl });

export const fetchProposals = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Proposal[]> =>
  call({ method: "GET", path: "/api/optimizer/proposals", query: { limit: "50" }, label: "GET /api/optimizer/proposals", schema: ProposalListSchema, signal, fetchImpl });

export const createProposal = (body: ProposalBody, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Proposal> =>
  call({ method: "POST", path: "/api/optimizer/proposals", label: "POST /api/optimizer/proposals", schema: ProposalSchema, body, signal, fetchImpl });

export const decideProposal = (
  id: number,
  decision: "approve" | "reject",
  note: string,
  signal?: AbortSignal,
  fetchImpl?: typeof fetch,
): Promise<Proposal> => {
  const text = note.trim();
  return call({
    method: "POST",
    path: `/api/optimizer/proposals/${encodeURIComponent(String(id))}/decision`,
    label: "POST /api/optimizer/proposals/{id}/decision",
    schema: ProposalSchema,
    body: text ? { decision, note: text } : { decision },
    signal,
    fetchImpl,
  });
};

export const fetchShadowSummary = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<ShadowSummary> =>
  call({ method: "GET", path: "/api/shadow_mode/summary", query: { limit: "500" }, label: "GET /api/shadow_mode/summary", schema: ShadowSchema, signal, fetchImpl });

/** Operator only. A 503 (`model_unavailable`) means there is no policy to shadow. The response body is not used. */
export const postShadowSample = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<unknown> =>
  call({ method: "POST", path: "/api/shadow_mode/sample", label: "POST /api/shadow_mode/sample", schema: ShadowSampleSchema, signal, fetchImpl });
