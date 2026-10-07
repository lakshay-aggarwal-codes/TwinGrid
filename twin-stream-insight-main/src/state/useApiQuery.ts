import { useMemo } from 'react';
import { useQuery, type QueryKey, type UseQueryOptions, type UseQueryResult } from '@tanstack/react-query';
import type { ApiError } from '@/api/apiError';
import { dataStateFromError, type DataState } from './dataState';

export interface UseApiQueryOptions<T> extends Omit<UseQueryOptions<T, ApiError, T, QueryKey>, 'throwOnError'> {
  /** Backend returned successfully but with no items. */
  isEmpty?: (data: T) => boolean;
  /** Backend says the evaluation/run has not been executed. */
  isNotRun?: (data: T) => boolean;
  /** Labels of optional fields the backend did not report. */
  missingFields?: (data: T) => readonly string[];
}

export interface UseApiQueryResult<T> {
  state: DataState<T>;
  refetch: () => void;
  query: UseQueryResult<T, ApiError>;
}

/**
 * FE-03: thin wrapper over React Query that returns a `DataState<T>`.
 * `ApiError.kind` selects the state; message text is never carried into it.
 * Precedence once data exists: a failed refetch (last-good data, labelled stale) > not_run > empty > ready.
 */
export function useApiQuery<T>(options: UseApiQueryOptions<T>): UseApiQueryResult<T> {
  const { isEmpty, isNotRun, missingFields, ...queryOptions } = options;
  const query = useQuery<T, ApiError, T, QueryKey>(queryOptions);
  const { data, status, fetchStatus, error, isRefetchError } = query;

  const state = useMemo<DataState<T>>(() => {
    if (data === undefined) {
      if (status === 'error') return dataStateFromError(error);
      if (status === 'pending' && fetchStatus === 'paused') return { status: 'error', kind: 'network' };
      return { status: 'loading' };
    }
    if (isRefetchError) return { status: 'ready', data, freshness: 'stale', refreshFailed: true };
    if (isNotRun?.(data)) return { status: 'not_run' };
    if (isEmpty?.(data)) return { status: 'empty' };
    const incomplete = missingFields?.(data);
    return incomplete && incomplete.length > 0
      ? { status: 'ready', data, incomplete }
      : { status: 'ready', data };
    // The predicates are expected to be stable or cheap; they are intentionally not dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, status, fetchStatus, error, isRefetchError]);

  return { state, refetch: () => void query.refetch(), query };
}
