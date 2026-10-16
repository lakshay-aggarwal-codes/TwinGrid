import { useEffect, useState } from "react";
import { fetchCapacity } from "./api";
import type { Capacity } from "./schema";
import type { Plan } from "./model";
import { whatIfParams } from "@/hooks/useWhatIf";
import type { SimConfig } from "@/hooks/useSimulation";
import { useApiQuery, type UseApiQueryResult } from "@/state/useApiQuery";

export const CAPACITY_STALE_MS = 60_000;
/** Inputs settle for this long before a request is made (the endpoint is two 24 h twin runs, rate limited). */
export const CAPACITY_DEBOUNCE_MS = 800;

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

export function useCapacity(
  config: Pick<SimConfig, "serverUtil" | "outsideTemp" | "waterStress" | "coolingMode" | "chilledWaterSetpoint">,
  plan: Plan,
  enabled = true,
): UseApiQueryResult<Capacity> {
  const params = useDebounced(whatIfParams(config), CAPACITY_DEBOUNCE_MS);
  return useApiQuery<Capacity>({
    queryKey: ["capacity", params, plan],
    queryFn: ({ signal }) => fetchCapacity(params, plan, signal),
    enabled,
    staleTime: CAPACITY_STALE_MS,
    retry: false,
    refetchOnWindowFocus: false,
  });
}
