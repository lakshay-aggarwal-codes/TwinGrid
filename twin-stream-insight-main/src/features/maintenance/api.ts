/**
 * Task 28: `/api/maintenance/*`. Same discipline as the alerts centre: bearer token from the auth client, one
 * refresh-and-retry on 401 (a 401 processed nothing, so replaying a write is safe), errors reduced to an `ApiError` kind
 * (never the body text), and every body parsed against its schema ("contract" on a mismatch, never repaired).
 */
import type { z } from "zod";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import type { CreateBody } from "./model";
import { HealthSchema, WorkOrderListSchema, WorkOrderSchema, type Health, type WorkOrder } from "./schema";

export const HEALTH_HOURS = 24;
export const healthKey = (hours: number) => ["maintenance-health", hours] as const;
export const ordersKey = (status: string | null) => ["work-orders", status] as const;
export const ORDERS_ROOT = ["work-orders"] as const;

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
  method: "GET" | "POST";
  path: string;
  /** Used only in error reports, never with an id or user text in it. */
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
    reportError("maintenance.network", `Request to ${c.label} failed`, "warning");
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
    reportError("maintenance.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(url, token, c);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("maintenance.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(url, fresh, c);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("maintenance.http", `${response.status} ${c.label}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("maintenance.http", `${response.status} ${c.label}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(c.schema, body, c.label);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}

export const fetchMaintenanceHealth = (hours: number, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Health> =>
  call({ method: "GET", path: `/api/maintenance/health?hours=${hours}`, label: "GET /api/maintenance/health", schema: HealthSchema, signal, fetchImpl });

export const fetchWorkOrders = (status: string | null, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<WorkOrder[]> =>
  call({
    method: "GET",
    path: `/api/maintenance/work-orders?limit=200${status ? `&status=${encodeURIComponent(status)}` : ""}`,
    label: "GET /api/maintenance/work-orders",
    schema: WorkOrderListSchema,
    signal,
    fetchImpl,
  });

/** Resolves to the SERVER's row; the UI shows that, never an optimistic guess. */
export const createWorkOrder = (body: CreateBody, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<WorkOrder> =>
  call({ method: "POST", path: "/api/maintenance/work-orders", label: "POST /api/maintenance/work-orders", schema: WorkOrderSchema, body, signal, fetchImpl });

export const changeWorkOrderStatus = (id: number, status: string, note: string | null, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<WorkOrder> =>
  call({
    method: "POST",
    path: `/api/maintenance/work-orders/${encodeURIComponent(String(id))}/status`,
    label: "POST /api/maintenance/work-orders/{id}/status",
    schema: WorkOrderSchema,
    body: note ? { status, note } : { status },
    signal,
    fetchImpl,
  });
