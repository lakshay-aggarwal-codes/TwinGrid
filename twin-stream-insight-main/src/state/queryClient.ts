/**
 * FE-03: QueryClient defaults. Explicit `staleTime`; no retry on 4xx; bounded retry for transient failures.
 *
 * "Abort on unmount": TanStack Query v5 cancels an in-flight query when its last observer unmounts, provided
 * the queryFn consumes the `signal` from its context. Every `apiClient` fetcher already accepts an `AbortSignal`,
 * so query functions should forward `({ signal }) => fetchX(params, signal)`.
 */
import { QueryClient } from '@tanstack/react-query';
import { isApiError } from '@/api/apiError';

export const QUERY_STALE_TIME_MS = 30_000;
const MAX_TRANSIENT_RETRIES = 2;

/** No retry for anything the client or contract caused (4xx, contract mismatch); a few retries for transient failures. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_TRANSIENT_RETRIES) return false;
  if (!isApiError(error)) return false;
  if (error.status !== undefined && error.status >= 400 && error.status < 500 && error.status !== 429) return false;
  switch (error.kind) {
    case 'network':
    case 'unavailable':
    case 'server':
      return true;
    default:
      return false; // unauthenticated, forbidden, not_found, conflict, rate_limited, validation, contract
  }
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: QUERY_STALE_TIME_MS,
        retry: shouldRetryQuery,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
