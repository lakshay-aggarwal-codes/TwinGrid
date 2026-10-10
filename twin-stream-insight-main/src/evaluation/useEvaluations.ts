import { fetchEvaluation, fetchEvaluations } from '@/api/apiClient';
import { useApiQuery, type UseApiQueryResult } from '@/state/useApiQuery';
import type { EvaluationList, EvaluationResult } from './schema';

/** Reports change when someone runs the harness, not by the minute. */
export const EVALUATION_STALE_MS = 60_000;

/** The list as a `DataState`: no reports at all is `not_run` ("no evaluation has been run"), never an empty table. */
export function useEvaluationList(): UseApiQueryResult<EvaluationList> {
  return useApiQuery<EvaluationList>({
    queryKey: ['evaluations'],
    queryFn: ({ signal }) => fetchEvaluations(signal),
    staleTime: EVALUATION_STALE_MS,
    refetchOnWindowFocus: false,
    isNotRun: (r) => r.evaluations.length === 0,
  });
}

export function useEvaluation(id: string | null): UseApiQueryResult<EvaluationResult> {
  return useApiQuery<EvaluationResult>({
    queryKey: ['evaluation', id],
    queryFn: ({ signal }) => fetchEvaluation(id as string, signal),
    enabled: id !== null,
    staleTime: EVALUATION_STALE_MS,
    refetchOnWindowFocus: false,
  });
}
