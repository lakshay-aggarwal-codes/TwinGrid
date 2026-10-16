import { useEffect, useState } from "react";
import { useApiQuery, type UseApiQueryResult } from "@/state/useApiQuery";
import { fetchCarbonSchedule, type ScheduleRequest } from "./api";
import type { CarbonSchedule } from "./schema";

export const SCHEDULE_STALE_MS = 60_000;
/** Typing settles for this long before a request is made. */
export const SCHEDULE_DEBOUNCE_MS = 500;

function useDebounced<T>(value: T, ms: number): T {
  const key = JSON.stringify(value);
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
    // `key` stands for the value's content; the object identity changes on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms]);
  return v;
}

/** `enabled=false` (invalid entries) makes no request at all. */
export function useCarbonSchedule(req: ScheduleRequest, enabled = true): UseApiQueryResult<CarbonSchedule> {
  const settled = useDebounced(req, SCHEDULE_DEBOUNCE_MS);
  return useApiQuery<CarbonSchedule>({
    queryKey: ["carbon-schedule", settled],
    queryFn: ({ signal }) => fetchCarbonSchedule(settled, signal),
    enabled,
    staleTime: SCHEDULE_STALE_MS,
    retry: false,
    refetchOnWindowFocus: false,
  });
}
