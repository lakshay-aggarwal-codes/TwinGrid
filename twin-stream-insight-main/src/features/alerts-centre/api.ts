/**
 * Task 17: `GET /api/alerts/inbox`, `GET /api/alerts/{id}/events`, `PATCH /api/alerts/{id}`.
 *
 * Same discipline as `src/api/alerts.ts`: bearer token from the auth client, one refresh-and-retry on 401 (nothing was
 * processed on a 401, so replaying the PATCH is safe), errors reduced to an `ApiError` kind (never the body text), and
 * every body parsed against its schema: a payload that does not match is "contract", never repaired.
 */
import type { z } from "zod";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { INBOX_LIMIT, InboxAlertSchema, InboxSchema, TimelineSchema, type AlertPatch, type InboxAlert, type Timeline } from "./model";

export const alertsInboxKey = ["alerts-inbox", INBOX_LIMIT] as const;
export const timelineKey = (id: number) => ["alert-timeline", id] as const;

export const inboxPath = () => `/api/alerts/inbox?limit=${INBOX_LIMIT}`;
export const timelinePath = (id: number) => `/api/alerts/${encodeURIComponent(String(id))}/events`;
export const patchPath = (id: number) => `/api/alerts/${encodeURIComponent(String(id))}`;

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
  method: "GET" | "PATCH";
  path: string;
  /** Used only in error reports, never with an id or any user text in it. */
  label: string;
  schema: S;
  body?: unknown;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

async function send(url: string, token: string, c: Call<z.ZodTypeAny>): Promise<Response> {
  const fetchImpl = c.fetchImpl ?? fetch;
  try {
    return await fetchImpl(url, {
      method: c.method,
      signal: c.signal,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(c.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: c.body === undefined ? undefined : JSON.stringify(c.body),
    });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("alerts-centre.network", `Request to ${c.label} failed`, "warning");
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
    reportError("alerts-centre.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(url, token, c);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("alerts-centre.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(url, fresh, c);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("alerts-centre.http", `${response.status} ${c.label}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("alerts-centre.http", `${response.status} ${c.label}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(c.schema, body, c.label);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}

export function fetchInbox(signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<InboxAlert[]> {
  return call({ method: "GET", path: inboxPath(), label: "GET /api/alerts/inbox", schema: InboxSchema, signal, fetchImpl });
}

export function fetchTimeline(id: number, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Timeline> {
  return call({ method: "GET", path: timelinePath(id), label: "GET /api/alerts/{id}/events", schema: TimelineSchema, signal, fetchImpl });
}

/** Resolves to the SERVER's row; the UI shows that, never an optimistic guess. */
export function patchAlert(id: number, body: AlertPatch, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<InboxAlert> {
  return call({ method: "PATCH", path: patchPath(id), label: "PATCH /api/alerts/{id}", schema: InboxAlertSchema, body, signal, fetchImpl });
}
