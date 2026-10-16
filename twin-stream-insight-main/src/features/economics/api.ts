/**
 * Task 25: `GET /api/economics/summary`. Same discipline as `what-if-lab/sensitivityApi.ts`: bearer token from the auth
 * client, one refresh-and-retry on 401, errors reduced to an `ApiError` kind (never body or message text), body parsed
 * against its schema (a mismatch is "unavailable", never repaired).
 */
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import type { WhatIfParams } from "@/api/apiClient";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { EconomicsSchema, type Economics } from "./schema";
import { tariffQuery, type TariffSettings } from "./tariff";

export const ECONOMICS_PATH = "/api/economics/summary";

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

export function economicsUrl(params: WhatIfParams, tariff: TariffSettings): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) q.set(k, String(v));
  for (const [k, v] of Object.entries(tariffQuery(tariff))) q.set(k, v);
  return new URL(`${ECONOMICS_PATH}?${q.toString()}`, API_BASE_URL).toString();
}

async function get(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { method: "GET", signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("economics.network", `Request to ${ECONOMICS_PATH} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

export async function fetchEconomics(params: WhatIfParams, tariff: TariffSettings, signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<Economics> {
  assertApiConfigured();
  const url = economicsUrl(params, tariff);
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("economics.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await get(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("economics.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await get(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("economics.http", `${response.status} ${ECONOMICS_PATH}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("economics.http", `${response.status} ${ECONOMICS_PATH}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(EconomicsSchema, body, "GET /api/economics/summary");
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}
