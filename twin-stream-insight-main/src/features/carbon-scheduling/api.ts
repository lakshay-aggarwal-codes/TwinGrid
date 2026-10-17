/**
 * Task 27: `GET /api/carbon/schedule`. Same discipline as `economics/api.ts`: bearer token from the auth client, one
 * refresh-and-retry on 401, errors reduced to an `ApiError` kind (never body or message text), body parsed against its
 * schema (a mismatch is a contract error, never repaired).
 */
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { CarbonScheduleSchema, type CarbonSchedule } from "./schema";

export const CARBON_SCHEDULE_PATH = "/api/carbon/schedule";

export interface ScheduleRequest {
  durationH: number;
  loadKw: number;
  /** Ask for the explicitly labelled synthetic demonstration profile instead of the loaded carbon data. */
  synthetic: boolean;
}

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

export function scheduleUrl(req: ScheduleRequest): string {
  const q = new URLSearchParams();
  q.set("duration_h", String(req.durationH));
  q.set("load_kw", String(req.loadKw));
  q.set("profile", req.synthetic ? "synthetic_demo" : "data");
  return new URL(`${CARBON_SCHEDULE_PATH}?${q.toString()}`, API_BASE_URL).toString();
}

async function get(url: string, token: string, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, { method: "GET", signal, headers: { Authorization: `Bearer ${token}` } });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("carbon.network", `Request to ${CARBON_SCHEDULE_PATH} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

export async function fetchCarbonSchedule(req: ScheduleRequest, signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<CarbonSchedule> {
  assertApiConfigured();
  const url = scheduleUrl(req);
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("carbon.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await get(url, token, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("carbon.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await get(url, fresh, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("carbon.http", `${response.status} ${CARBON_SCHEDULE_PATH}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("carbon.http", `${response.status} ${CARBON_SCHEDULE_PATH}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(CarbonScheduleSchema, body, "GET /api/carbon/schedule");
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}
