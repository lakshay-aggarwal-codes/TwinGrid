/**
 * Task 29: `/api/admin/*`. Same discipline as the other features: bearer token from the auth client, one refresh-and-retry
 * on 401 (a 401 processed nothing, so replaying a write is safe), errors reduced to an `ApiError` kind (never the body
 * text), and every JSON body parsed against its schema ("contract" on a mismatch, never repaired).
 */
import type { z } from "zod";
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import {
  AuditSchema,
  DeliveriesSchema,
  SystemSchema,
  TestResultSchema,
  UserSchema,
  UsersSchema,
  WebhooksSchema,
  type AuditPage,
  type Deliveries,
  type SystemStatus,
  type TestResult,
  type User,
  type Users,
  type Webhooks,
} from "./schema";

export const KEYS = {
  users: ["admin-users"] as const,
  audit: (qs: string) => ["admin-audit", qs] as const,
  webhooks: ["admin-webhooks"] as const,
  deliveries: (webhookId: string | null) => ["admin-deliveries", webhookId] as const,
  system: ["admin-system"] as const,
};
export const AUDIT_ROOT = ["admin-audit"] as const;
export const DELIVERIES_ROOT = ["admin-deliveries"] as const;

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

type Method = "GET" | "POST" | "PUT" | "DELETE";

interface Req {
  method: Method;
  path: string;
  /** Used only in error reports: never an id or user text. */
  label: string;
  body?: unknown;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

async function send(url: string, token: string, r: Req): Promise<Response> {
  try {
    return await (r.fetchImpl ?? fetch)(url, {
      method: r.method,
      signal: r.signal,
      headers: { Authorization: `Bearer ${token}`, ...(r.body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: r.body === undefined ? undefined : JSON.stringify(r.body),
    });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("admin.network", `Request to ${r.label} failed`, "warning");
    throw new ApiError({ kind: "network" });
  }
}

/** The authorised request with its one refresh-and-retry, returning a successful Response or throwing. */
async function authed(r: Req): Promise<Response> {
  assertApiConfigured();
  const url = new URL(r.path, API_BASE_URL).toString();
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("admin.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(url, token, r);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("admin.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(url, fresh, r);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("admin.http", `${response.status} ${r.label}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  return response;
}

async function call<S extends z.ZodTypeAny>(r: Req, schema: S): Promise<z.output<S>> {
  const response = await authed(r);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    reportError("admin.http", `${response.status} ${r.label}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(schema, body, r.label);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}

// ------------------------------------------------------------------------------------------ users
export const fetchUsers = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Users> =>
  call({ method: "GET", path: "/api/admin/users", label: "GET /api/admin/users", signal, fetchImpl }, UsersSchema);

/** Resolves to the SERVER's row; the list is refetched afterwards, never patched optimistically. */
export const changeRole = (id: number, role: string, fetchImpl?: typeof fetch): Promise<User> =>
  call(
    { method: "POST", path: `/api/admin/users/${encodeURIComponent(String(id))}/role`, label: "POST /api/admin/users/{id}/role", body: { role }, fetchImpl },
    UserSchema,
  );

// ------------------------------------------------------------------------------------------ audit
export const fetchAudit = (query: string, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<AuditPage> =>
  call({ method: "GET", path: `/api/admin/audit?${query}`, label: "GET /api/admin/audit", signal, fetchImpl }, AuditSchema);

export interface ExportResult {
  blob: Blob;
  filename: string;
  rows: number;
  truncated: boolean;
}

/** The export as a file the browser can save. The filename comes from the server's header; a fallback is used if absent. */
export async function downloadAudit(query: string, format: "csv" | "json", fetchImpl?: typeof fetch): Promise<ExportResult> {
  const params = new URLSearchParams(query);
  params.set("format", format);
  const response = await authed({ method: "GET", path: `/api/admin/audit/export?${params.toString()}`, label: "GET /api/admin/audit/export", fetchImpl });
  const blob = await response.blob();
  const disposition = response.headers?.get?.("Content-Disposition") ?? "";
  const match = /filename="([^"\\/]+)"/.exec(disposition);
  return {
    blob,
    filename: match ? match[1] : `audit-log.${format}`,
    rows: Number(response.headers?.get?.("X-Export-Rows") ?? "0") || 0,
    truncated: response.headers?.get?.("X-Export-Truncated") === "true",
  };
}

// ------------------------------------------------------------------------------------------ webhooks
export const fetchWebhooks = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Webhooks> =>
  call({ method: "GET", path: "/api/admin/webhooks", label: "GET /api/admin/webhooks", signal, fetchImpl }, WebhooksSchema);

export const createWebhook = (url: string, fetchImpl?: typeof fetch): Promise<Webhooks> =>
  call({ method: "POST", path: "/api/admin/webhooks", label: "POST /api/admin/webhooks", body: { url }, fetchImpl }, WebhooksSchema);

export const replaceWebhook = (id: string, url: string, fetchImpl?: typeof fetch): Promise<Webhooks> =>
  call({ method: "PUT", path: `/api/admin/webhooks/${encodeURIComponent(id)}`, label: "PUT /api/admin/webhooks/{id}", body: { url }, fetchImpl }, WebhooksSchema);

export const deleteWebhook = (id: string, fetchImpl?: typeof fetch): Promise<Webhooks> =>
  call({ method: "DELETE", path: `/api/admin/webhooks/${encodeURIComponent(id)}`, label: "DELETE /api/admin/webhooks/{id}", fetchImpl }, WebhooksSchema);

export const testWebhook = (id: string, fetchImpl?: typeof fetch): Promise<TestResult> =>
  call({ method: "POST", path: `/api/admin/webhooks/${encodeURIComponent(id)}/test`, label: "POST /api/admin/webhooks/{id}/test", fetchImpl }, TestResultSchema);

export const fetchDeliveries = (webhookId: string | null, signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<Deliveries> =>
  call(
    {
      method: "GET",
      path: `/api/admin/webhooks/deliveries?limit=50${webhookId ? `&webhook_id=${encodeURIComponent(webhookId)}` : ""}`,
      label: "GET /api/admin/webhooks/deliveries",
      signal,
      fetchImpl,
    },
    DeliveriesSchema,
  );

// ------------------------------------------------------------------------------------------ system
export const fetchSystem = (signal?: AbortSignal, fetchImpl?: typeof fetch): Promise<SystemStatus> =>
  call({ method: "GET", path: "/api/admin/system", label: "GET /api/admin/system", signal, fetchImpl }, SystemSchema);
