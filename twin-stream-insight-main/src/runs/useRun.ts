import { useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchRun, fetchRunResult, submitRun, type RunSubmitBody } from '@/api/apiClient.ts';
import type { ApiError } from '@/api/apiError.ts';
import { useApiQuery, type UseApiQueryResult } from '@/state/useApiQuery';
import { describeStatus, pollInterval } from './model';
import type { RunRecord, RunResult } from './schema';

/** One shared definition, so the status poll and the result panel read the same cache entry. */
const resultKey = (id: string) => ['run-result', id] as const;
const resultQuery = (id: string) => ({
  queryKey: resultKey(id),
  queryFn: ({ signal }: { signal: AbortSignal }) => fetchRunResult(id, signal),
  staleTime: Infinity,
});

/**
 * One run's status. React Query owns the polling schedule (`pollInterval`); this page has no timers of its own.
 * The moment the backend answers `completed` for this run, the result request starts from here (once, shared with
 * `useRunResult`), so the result does not wait for an extra render pass. Nothing is requested before `completed`.
 */
export function useRunStatus(id: string): UseApiQueryResult<RunRecord> {
  const client = useQueryClient();
  return useApiQuery<RunRecord>({
    queryKey: ['run', id],
    queryFn: async ({ signal }) => {
      const record = await fetchRun(id, signal);
      if (record.run_id === id && describeStatus(record.status).id === 'completed') void client.prefetchQuery(resultQuery(id));
      return record;
    },
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => pollInterval(query.state),
  });
}

/** The result, shown only when `enabled` (the status is `completed`). Fetched once; a failed fetch is not retried by mounting. */
export function useRunResult(id: string, enabled: boolean): UseApiQueryResult<RunResult> {
  return useApiQuery<RunResult>({
    ...resultQuery(id),
    enabled,
    retryOnMount: false,
    refetchOnWindowFocus: false,
  });
}

export function useSubmitRun() {
  return useMutation<RunRecord, ApiError, RunSubmitBody>({ mutationFn: (body) => submitRun(body) });
}
