import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchWhatIf, type WhatIfParams, type WhatIfResponse } from "@/api/apiClient";
import { ApiError } from "@/api/apiError";
import { useApiQuery, type UseApiQueryResult } from "@/state/useApiQuery";
import { fetchRecommendation } from "../optimizer-approvals/api";
import type { Context } from "../optimizer-approvals/model";
import { createDebouncer } from "./debounce";
import { BACKEND_WHATIF_SETPOINT_C, setpointRangeOf, toParams, type LabInputs, type SetpointRange } from "./model";
import { fetchSensitivity } from "./sensitivityApi";
import { STORAGE_KEY, parseSavedList, serializeSaved, type SavedScenario } from "./saved";
import type { Sweep } from "./schema";

/** One backend run is a constant-input preview: the same inputs are not refetched for a minute (same as the existing What-If tab). */
export const RUN_STALE_MS = 60_000;
export const DEBOUNCE_MS = 400;
/** The set-point range follows the server's physics, which does not change while the page is open. */
export const RANGE_STALE_MS = 10 * 60_000;
export const RANGE_QUERY_KEY = ["whatif-lab-setpoint-range"] as const;

/** The backend's what-if defaults as an optimizer context: only the `setpoint_check` of the answer is used. */
const RANGE_PROBE: Context = {
  utilisation: 0.65,
  outside_temp: 22,
  water_stress: 0,
  mode: "auto",
  chilled_water_temp: BACKEND_WHATIF_SETPOINT_C,
  inlet_temp_c: null,
};

/**
 * The chilled-water set-point range for the physics the server runs, from `setpoint_check.actuator_range_C` of
 * `GET /api/optimizer/baseline-recommendation` (the field the recommendation form reads). No endpoint exposes the
 * what-if range directly. An answer with no usable range is "unavailable": the lab does not guess one.
 */
export function useSetpointRange(): UseApiQueryResult<SetpointRange> {
  return useApiQuery<SetpointRange>({
    queryKey: RANGE_QUERY_KEY,
    queryFn: async ({ signal }) => {
      const recommendation = await fetchRecommendation(RANGE_PROBE, signal);
      const range = setpointRangeOf(recommendation.predicted);
      if (range === null) throw new ApiError({ kind: "unavailable" });
      return range;
    },
    staleTime: RANGE_STALE_MS,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** `value` after `ms` of quiet. The first value is immediate, so the page never opens on an empty state. */
export function useDebouncedInputs(value: LabInputs, ms: number = DEBOUNCE_MS): LabInputs {
  const [settled, setSettled] = useState(value);
  const deb = useRef(createDebouncer<LabInputs>(ms, setSettled));
  useEffect(() => {
    const d = (deb.current = createDebouncer<LabInputs>(ms, setSettled));
    return () => d.cancel();
  }, [ms]);
  useEffect(() => {
    deb.current.push(value);
    // The content, not the object identity, decides whether a new run is scheduled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.itLoadPct, value.ambientC, value.setpointC, value.mode]);
  return settled;
}

/** One isolated 24 h what-if run (`GET /api/whatif`, read-only: nothing is persisted, ADR 007). The query key matches the existing What-If tab's. */
export function useRun(inputs: LabInputs): UseApiQueryResult<WhatIfResponse> & { params: WhatIfParams } {
  const params = useMemo(() => toParams(inputs), [inputs.itLoadPct, inputs.ambientC, inputs.setpointC, inputs.mode]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useApiQuery<WhatIfResponse>({
    queryKey: ["whatif", params],
    queryFn: ({ signal }) => fetchWhatIf(params, signal),
    staleTime: RUN_STALE_MS,
    refetchOnWindowFocus: false,
  });
  return { ...q, params };
}

/** The sensitivity sweep runs only when asked (the backend limits it to 6 requests a minute), and its result stays tied to the inputs it was computed for. */
export function useSweep(): { request: (i: LabInputs) => void; for: LabInputs | null; result: UseApiQueryResult<Sweep> } {
  const [requested, setRequested] = useState<LabInputs | null>(null);
  const params = requested ? toParams(requested) : null;
  const result = useApiQuery<Sweep>({
    queryKey: ["whatif-sensitivity", params],
    queryFn: ({ signal }) => fetchSensitivity(params as WhatIfParams, signal),
    enabled: params !== null,
    staleTime: RUN_STALE_MS,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const request = useCallback((i: LabInputs) => setRequested(i), []);
  return { request, for: requested, result };
}

/** Saved scenarios in this browser (inputs and the numbers the backend returned). Reads and writes never throw: storage can be unavailable. */
export function useSavedScenarios(): { list: SavedScenario[]; set: (next: SavedScenario[]) => void; storageOk: boolean } {
  const [state, setState] = useState<{ list: SavedScenario[]; ok: boolean }>(() => {
    try {
      return { list: parseSavedList(window.localStorage.getItem(STORAGE_KEY)), ok: true };
    } catch {
      return { list: [], ok: false };
    }
  });
  const set = useCallback((next: SavedScenario[]) => {
    setState((s) => {
      let ok = s.ok;
      try {
        window.localStorage.setItem(STORAGE_KEY, serializeSaved(next));
        ok = true;
      } catch {
        ok = false;
      }
      return { list: next, ok };
    });
  }, []);
  return { list: state.list, set, storageOk: state.ok };
}
