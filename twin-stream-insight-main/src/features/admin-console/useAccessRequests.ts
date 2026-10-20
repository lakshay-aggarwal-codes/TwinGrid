import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { isApiError } from "@/api/apiError";
import { useApiQuery } from "@/state/useApiQuery";
import {
  ACCESS_ROOT,
  AUDIT_ROOT,
  KEYS,
  decideAccessRequest,
  fetchAccessRequest,
  fetchAccessRequests,
  resendAccessActivation,
  resendAccessNotification,
  type AccessDecision,
} from "./api";
import type { AccessRequest, AccessRequests } from "./schema";

/** One page of the queue. `query` is a built query string (status, limit, cursor). */
export function useAccessRequests(query: string) {
  return useApiQuery<AccessRequests>({
    queryKey: KEYS.accessList(query),
    queryFn: ({ signal }) => fetchAccessRequests(query, signal),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    isEmpty: (p) => p.items.length === 0,
  });
}

/** One request, fetched only while its detail (the admin-only decision note) is open. */
export function useAccessRequest(id: string, enabled: boolean) {
  return useApiQuery<AccessRequest>({
    queryKey: KEYS.accessOne(id),
    queryFn: ({ signal }) => fetchAccessRequest(id, signal),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Writes resolve to the SERVER's answer and the queue is then refetched, never patched optimistically. A 409 or 404 also
 * refetches (the row changed under the admin), and the error is still thrown so the panel can say so.
 */
export function useAccessActions() {
  const client = useQueryClient();
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: ACCESS_ROOT });
    await client.invalidateQueries({ queryKey: AUDIT_ROOT });
  }, [client]);
  const guarded = useCallback(
    async <T,>(call: () => Promise<T>): Promise<T> => {
      try {
        const result = await call();
        await refresh();
        return result;
      } catch (e) {
        if (isApiError(e) && (e.kind === "conflict" || e.kind === "not_found")) await refresh();
        throw e;
      }
    },
    [refresh],
  );
  const decide = useCallback((id: string, decision: AccessDecision, note: string | null) => guarded(() => decideAccessRequest(id, decision, note)), [guarded]);
  const resendNotification = useCallback((id: string) => guarded(() => resendAccessNotification(id)), [guarded]);
  const resendActivation = useCallback((id: string) => guarded(() => resendAccessActivation(id)), [guarded]);
  return { decide, resendNotification, resendActivation };
}
