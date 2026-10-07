import { describe, it, expect } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/api/apiError';
import { useApiQuery } from './useApiQuery';
import { createAppQueryClient, shouldRetryQuery, QUERY_STALE_TIME_MS } from './queryClient';

const wrap = (client = new QueryClient()) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };

describe('useApiQuery', () => {
  it('loading, then ready', async () => {
    const { result } = renderHook(() => useApiQuery({ queryKey: ['ok'], queryFn: async () => [1, 2], retry: false }), { wrapper: wrap() });
    expect(result.current.state).toEqual({ status: 'loading' });
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(result.current.state).toMatchObject({ status: 'ready', data: [1, 2] });
  });

  it('maps ApiError.kind to state; backend text never enters it', async () => {
    const { result } = renderHook(
      () => useApiQuery({ queryKey: ['net'], queryFn: async () => { throw new ApiError({ kind: 'network' }); }, retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state).toEqual({ status: 'error', kind: 'network', code: undefined });
  });

  it('403 -> unauthorized/forbidden; 401 -> unauthorized/session_expired', async () => {
    const forbidden = renderHook(
      () => useApiQuery({ queryKey: ['403'], queryFn: async () => { throw new ApiError({ kind: 'forbidden', status: 403 }); }, retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(forbidden.result.current.state.status).toBe('unauthorized'));
    expect(forbidden.result.current.state).toEqual({ status: 'unauthorized', reason: 'forbidden' });

    const expired = renderHook(
      () => useApiQuery({ queryKey: ['401'], queryFn: async () => { throw new ApiError({ kind: 'unauthenticated', status: 401 }); }, retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(expired.result.current.state.status).toBe('unauthorized'));
    expect(expired.result.current.state).toEqual({ status: 'unauthorized', reason: 'session_expired' });
  });

  it('empty and not_run come from predicates, and are distinct', async () => {
    const empty = renderHook(
      () => useApiQuery<number[]>({ queryKey: ['empty'], queryFn: async () => [], isEmpty: (d) => d.length === 0, retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(empty.result.current.state.status).toBe('empty'));

    const notRun = renderHook(
      () => useApiQuery<{ ran: boolean }>({ queryKey: ['nr'], queryFn: async () => ({ ran: false }), isNotRun: (d) => !d.ran, retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(notRun.result.current.state.status).toBe('not_run'));
  });

  it('reports missing optional fields as incomplete', async () => {
    const { result } = renderHook(
      () => useApiQuery<{ pue?: number }>({ queryKey: ['inc'], queryFn: async () => ({}), missingFields: (d) => (d.pue === undefined ? ['PUE'] : []), retry: false }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(result.current.state).toMatchObject({ incomplete: ['PUE'] });
  });

  it('a failed refetch keeps last-good data, labelled stale/refreshFailed', async () => {
    let calls = 0;
    const { result } = renderHook(
      () =>
        useApiQuery({
          queryKey: ['refetch'],
          queryFn: async () => {
            calls += 1;
            if (calls > 1) throw new ApiError({ kind: 'server', status: 500 });
            return 'good';
          },
          retry: false,
        }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    result.current.refetch();
    await waitFor(() => expect(result.current.state).toMatchObject({ status: 'ready', data: 'good', freshness: 'stale', refreshFailed: true }));
  });
});

describe('query defaults', () => {
  it('sets an explicit staleTime and the shared retry policy', () => {
    const q = createAppQueryClient().getDefaultOptions().queries!;
    expect(q.staleTime).toBe(QUERY_STALE_TIME_MS);
    expect(q.retry).toBe(shouldRetryQuery);
    expect(createAppQueryClient().getDefaultOptions().mutations?.retry).toBe(false);
  });

  it('never retries 4xx or contract errors; retries transient failures a bounded number of times', () => {
    for (const kind of ['unauthenticated', 'forbidden', 'not_found', 'conflict', 'rate_limited', 'validation', 'contract'] as const) {
      expect(shouldRetryQuery(0, new ApiError({ kind }))).toBe(false);
    }
    expect(shouldRetryQuery(0, new ApiError({ kind: 'validation', status: 422 }))).toBe(false);
    for (const kind of ['network', 'unavailable', 'server'] as const) {
      expect(shouldRetryQuery(0, new ApiError({ kind }))).toBe(true);
      expect(shouldRetryQuery(2, new ApiError({ kind }))).toBe(false);
    }
    expect(shouldRetryQuery(0, new Error('not an ApiError'))).toBe(false);
  });
});
