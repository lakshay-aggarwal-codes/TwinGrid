import { useEffect, useState } from "react";
import { fetchEconomics } from "./api";
import type { Economics } from "./schema";
import type { TariffSettings } from "./tariff";
import { whatIfParams } from "@/hooks/useWhatIf";
import type { SimConfig } from "@/hooks/useSimulation";
import { useApiQuery, type UseApiQueryResult } from "@/state/useApiQuery";

export const ECONOMICS_STALE_MS = 60_000;
/** Inputs settle for this long before a request is made (the endpoint is two 24 h twin runs, rate limited). */
export const ECONOMICS_DEBOUNCE_MS = 800;

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

export function useEconomics(config: Pick<SimConfig, "serverUtil" | "outsideTemp" | "waterStress" | "coolingMode" | "chilledWaterSetpoint">, tariff: TariffSettings): UseApiQueryResult<Economics> {
  const params = useDebounced(whatIfParams(config), ECONOMICS_DEBOUNCE_MS);
  return useApiQuery<Economics>({
    queryKey: ["economics", params, tariff],
    queryFn: ({ signal }) => fetchEconomics(params, tariff, signal),
    staleTime: ECONOMICS_STALE_MS,
    retry: false,
  });
}
