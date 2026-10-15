/**
 * Task 18: `GET /api/models/passport` and `GET /api/alerts/{id}/explanation`. Same discipline as the other feature
 * clients: bearer token, one refresh-and-retry on 401, errors reduced to an `ApiError` kind (never body text), and every
 * body parsed against its schema (a mismatch is "contract", never repaired). Read-only.
 */
import type { z } from "zod";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { ExplanationSchema, PassportSchema, type Explanation, type Passport } from "./model";

export const passportKey = ["model-passport"] as const;
export const explanationKey = (id: number) => ["alert-explanation", id] as const;
export const passportPath = () => "/api/models/passport";
export const explanationPath = (id: number) => `/api/alerts/${encodeURIComponent(String(id))}/explanation`;

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

interface Call<S extends z.ZodTypeAny> {
  path: string;
  label: string;
  schema: S;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

async function send(url: string, token: string, c: Call<z.ZodTypeAny>): Promise<Response> {
  try {
    return await (c.fetchImpl ?? fetch)(url, { method: "GET", signal: c.signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("explainability.network", `Request to ${c.label} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

async function call<S extends z.ZodTypeAny>(c: Call<S>): Promise<z.output<S>> {
  assertApiConfigured();
  const url = new URL(c.path, API_BASE_URL).toString();
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("explainability.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(url, token, c);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("explainability.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(url, fresh, c);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("explainability.http", `${response.status} ${c.label}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("explainability.http", `${response.status} ${c.label}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(c.schema, body, c.label);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}

export function fetchPassport(signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Passport> {
  return call({ path: passportPath(), label: "GET /api/models/passport", schema: PassportSchema, signal, fetchImpl });
}

export function fetchExplanation(id: number, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Explanation> {
  return call({ path: explanationPath(id), label: "GET /api/alerts/{id}/explanation", schema: ExplanationSchema, signal, fetchImpl });
}
