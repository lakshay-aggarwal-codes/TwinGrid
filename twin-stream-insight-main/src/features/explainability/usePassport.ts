import { useApiQuery, type UseApiQueryResult } from "@/state/useApiQuery";
import { fetchExplanation, fetchPassport, explanationKey, passportKey } from "./api";
import type { Explanation, Passport } from "./model";

/** The registry changes when someone trains or promotes a model, not by the minute. */
export const PASSPORT_STALE_MS = 60_000;

export function usePassport(enabled = true): UseApiQueryResult<Passport> {
  return useApiQuery<Passport>({
    queryKey: passportKey,
    queryFn: ({ signal }) => fetchPassport(signal),
    staleTime: PASSPORT_STALE_MS,
    refetchOnWindowFocus: false,
    enabled,
    isEmpty: (p) => p.models.length === 0,
  });
}

export function useAlertExplanation(alertId: number, enabled: boolean): UseApiQueryResult<Explanation> {
  return useApiQuery<Explanation>({
    queryKey: explanationKey(alertId),
    queryFn: ({ signal }) => fetchExplanation(alertId, signal),
    staleTime: PASSPORT_STALE_MS,
    refetchOnWindowFocus: false,
    enabled,
  });
}
