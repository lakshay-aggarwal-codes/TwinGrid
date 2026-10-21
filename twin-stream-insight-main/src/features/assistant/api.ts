/**
 * Task 15: `POST /api/copilot/ask`. Same discipline as `features/alerts-centre/api.ts`: bearer token from the auth
 * client, one refresh-and-retry on 401, failures reduced to an `ApiError` kind (never body text), the body parsed
 * against its schema (a mismatch is "contract", never repaired). The question and the answer are never logged.
 */
import { ApiError, parseRetryAfter, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError, forceRefresh, getToken } from "@/authClient";
import { API_BASE_URL, assertApiConfigured } from "@/config";
import { isFailure, parseApi } from "@/contract/parse";
import { reportError } from "@/lib/errorReporter";
import { CopilotResponseSchema, type AskBody, type CopilotResponse } from "./schema";

export const ASK_PATH = "/api/copilot/ask";

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "validation";
}

async function send(url: string, token: string, body: AskBody, signal: AbortSignal | undefined, fetchImpl: typeof fetch): Promise<Response> {
  try {
    return await fetchImpl(url, {
      method: "POST",
      signal,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    if (typeof e === "object" && e !== null && (e as { name?: unknown }).name === "AbortError") throw e;
    reportError("assistant.network", "Request to the assistant failed", "warning");
    throw new ApiError({ kind: "network" });
  }
}

export async function askCopilot(body: AskBody, signal?: AbortSignal, fetchImpl: typeof fetch = fetch): Promise<CopilotResponse> {
  assertApiConfigured();
  const url = new URL(ASK_PATH, API_BASE_URL).toString();
  let token: string;
  try {
    token = await getToken();
  } catch (e) {
    if (e instanceof AuthRequiredError) throw e;
    reportError("assistant.token", e, "warning");
    throw new ApiError({ kind: "unavailable" });
  }
  let response = await send(url, token, body, signal, fetchImpl);
  if (response.status === 401) {
    let fresh: string;
    try {
      fresh = await forceRefresh();
    } catch (e) {
      if (e instanceof AuthRequiredError) throw e;
      reportError("assistant.refresh", e, "warning");
      throw new ApiError({ kind: "unavailable" });
    }
    response = await send(url, fresh, body, signal, fetchImpl);
    if (response.status === 401) throw new AuthRequiredError();
  }
  if (!response.ok) {
    reportError("assistant.http", `${response.status} POST ${ASK_PATH}`, response.status >= 500 ? "error" : "warning");
    throw new ApiError({ kind: kindFor(response.status), status: response.status, retryAfterS: parseRetryAfter(response.headers?.get?.("Retry-After")) });
  }
  let json: unknown;
  try {
    json = await response.json();
  } catch {
    reportError("assistant.http", `${response.status} POST ${ASK_PATH}: body is not JSON`, "error");
    throw new ApiError({ kind: "server", status: response.status });
  }
  const parsed = parseApi(CopilotResponseSchema, json, `POST ${ASK_PATH}`);
  if (isFailure(parsed)) throw new ApiError({ kind: "contract", status: response.status });
  return parsed.data;
}
