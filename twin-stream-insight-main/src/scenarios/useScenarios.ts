import { fetchScenarios, fetchScenarioWhatIf, type WhatIfResponse } from '@/api/apiClient';
import { useApiQuery, type UseApiQueryResult } from '@/state/useApiQuery';
import { WHATIF_STALE_MS } from '@/hooks/useWhatIf';
import type { ScenarioRegistry } from './schema';
import type { ScenarioRunRequest } from './model';

/** The backend scenario registry as a `DataState`. Registry content changes with deployments, not by the minute. */
export const SCENARIOS_STALE_MS = 5 * 60_000;

export function useScenarios(): UseApiQueryResult<ScenarioRegistry> {
  return useApiQuery<ScenarioRegistry>({
    queryKey: ['scenarios'],
    queryFn: ({ signal }) => fetchScenarios(signal),
    staleTime: SCENARIOS_STALE_MS,
    refetchOnWindowFocus: false,
    isEmpty: (r) => r.scenarios.length === 0,
  });
}

/**
 * One scenario preview, only after the person asked for it (`request` stays null until then: no request on selection
 * or while typing). The request carries the scenario id; nothing is computed locally.
 */
export function useScenarioPreview(request: ScenarioRunRequest | null): UseApiQueryResult<WhatIfResponse> {
  return useApiQuery<WhatIfResponse>({
    queryKey: ['scenario-whatif', request],
    queryFn: ({ signal }) => fetchScenarioWhatIf(request as ScenarioRunRequest, signal),
    enabled: request !== null,
    staleTime: WHATIF_STALE_MS,
    refetchOnWindowFocus: false,
  });
}
