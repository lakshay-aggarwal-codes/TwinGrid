/**
 * Task 30: `GET /api/fleet/sites`. Same discipline as `what-if-lab/sensitivityApi.ts`: bearer token from the auth client,
 * one refresh-and-retry on 401, errors reduced to an `ApiError` kind (never body or message text), and the body parsed
 * against its schema; a payload that does not match is a contract error, never repaired.
 */
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { FleetSchema, type Fleet } from "./schema";

export const FLEET_PATH = "/api/fleet/sites";

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

async function get(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { method: "GET", signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("fleet.network", `Request to ${FLEET_PATH} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

export async function fetchFleet(signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<Fleet> {
  assertApiConfigured();
  const url = new URL(FLEET_PATH, API_BASE_URL).toString();
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("fleet.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await get(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("fleet.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await get(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("fleet.http", `${response.status} ${FLEET_PATH}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("fleet.http", `${response.status} ${FLEET_PATH}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(FleetSchema, body, "GET /api/fleet/sites");
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}
