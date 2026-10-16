/**
 * Task 26: `GET /api/capacity/headroom`. Same discipline as `economics/api.ts`: bearer token from the auth client, one
 * refresh-and-retry on 401, errors reduced to an `ApiError` kind (never body or message text), body parsed against its
 * schema (a mismatch is "unavailable", never repaired).
 */
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import type { WhatIfParams } from "@/api/apiClient";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { CapacitySchema, type Capacity } from "./schema";
import type { Plan } from "./model";

export const CAPACITY_PATH = "/api/capacity/headroom";

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

export function capacityUrl(params: WhatIfParams, plan: Plan): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) q.set(k, String(v));
  q.set("add_racks", String(plan.addRacks));
  q.set("kw_per_rack", String(plan.kwPerRack));
  return new URL(`${CAPACITY_PATH}?${q.toString()}`, API_BASE_URL).toString();
}

async function get(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { method: "GET", signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("capacity.network", `Request to ${CAPACITY_PATH} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

export async function fetchCapacity(params: WhatIfParams, plan: Plan, signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<Capacity> {
  assertApiConfigured();
  const url = capacityUrl(params, plan);
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("capacity.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await get(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("capacity.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await get(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("capacity.http", `${response.status} ${CAPACITY_PATH}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("capacity.http", `${response.status} ${CAPACITY_PATH}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(CapacitySchema, body, "GET /api/capacity/headroom");
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}
