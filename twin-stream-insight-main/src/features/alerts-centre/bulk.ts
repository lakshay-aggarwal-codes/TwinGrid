import { isApiError, type ApiErrorKind } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";

export interface BulkResult {
  done: number[];
  failed: { id: number; kind: ApiErrorKind | "auth" }[];
  /** Not attempted because an earlier failure made every later request pointless (rate limit, no permission, signed out). */
  skipped: number[];
}

const STOPS: ReadonlySet<string> = new Set(["rate_limited", "forbidden", "unauthenticated", "auth"]);

function kindOf(e: unknown): ApiErrorKind | "auth" {
  if (e instanceof AuthRequiredError) return "auth";
  return isApiError(e) ? e.kind : "network";
}

/**
 * Runs `apply` for each id, one at a time (so the backend's rate limit and the audit trail see ordinary requests).
 * A per-alert failure (409: someone else already moved it) is recorded and the run goes on; a failure that would
 * repeat for every alert stops the run and the rest are reported as skipped.
 */
export async function runBulk(
  ids: readonly number[],
  apply: (id: number) => Promise<unknown>,
  onProgress?: (completed: number, total: number) => void,
): Promise<BulkResult> {
  const result: BulkResult = { done: [], failed: [], skipped: [] };
  for (let i = 0; i < ids.length; i += 1) {
    try {
      await apply(ids[i]);
      result.done.push(ids[i]);
    } catch (e) {
      const kind = kindOf(e);
      result.failed.push({ id: ids[i], kind });
      if (STOPS.has(kind)) {
        result.skipped.push(...ids.slice(i + 1));
        onProgress?.(ids.length, ids.length);
        return result;
      }
    }
    onProgress?.(i + 1, ids.length);
  }
  return result;
}
