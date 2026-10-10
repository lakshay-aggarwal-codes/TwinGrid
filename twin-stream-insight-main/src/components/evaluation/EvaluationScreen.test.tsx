import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { CAPTURED_BASELINES_ONLY, CAPTURED_LIST, clone } from '@/evaluation/testFixtures';
import { expectState } from '@/state/testing';

const { fetchEvaluations, fetchEvaluation } = vi.hoisted(() => ({ fetchEvaluations: vi.fn(), fetchEvaluation: vi.fn() }));
vi.mock('@/api/apiClient', () => ({ fetchEvaluations, fetchEvaluation }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import Evaluation from '@/pages/Evaluation';

const renderAt = (path: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="/evaluation/:id" element={<Evaluation />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  fetchEvaluations.mockReset().mockResolvedValue(clone(CAPTURED_LIST));
  fetchEvaluation.mockReset().mockResolvedValue(clone(CAPTURED_BASELINES_ONLY));
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe('Evaluation page', () => {
  it('shows the newest listed report (the backend order) with the real baselines-only outcome', async () => {
    renderAt('/evaluation');
    expect(await screen.findByTestId('outcome-headline')).toHaveTextContent('Not evaluated — claim allowed: none');
    expect(fetchEvaluation).toHaveBeenCalledWith('baselines_only_0fcafef9d28fd539', expect.anything());
    expect(screen.getByText('Simulator results only. They describe policies run inside the simulator, not a real facility.')).toBeInTheDocument();
  });

  it('opens the report named in the URL', async () => {
    renderAt('/evaluation/baselines_only_0fcafef9d28fd539');
    await screen.findByTestId('evaluation-view');
    expect(fetchEvaluation).toHaveBeenCalledWith('baselines_only_0fcafef9d28fd539', expect.anything());
  });

  it('no reports at all is the not_run state, never an empty table', async () => {
    fetchEvaluations.mockResolvedValue({ evaluations: [] });
    renderAt('/evaluation');
    await waitFor(() => expectState('not_run', { text: 'No evaluation has been run' }));
    expect(screen.queryByTestId('evaluation-table')).not.toBeInTheDocument();
  });

  it('403 is "No permission", not a retry loop', async () => {
    fetchEvaluations.mockRejectedValue(new ApiError({ kind: 'forbidden', status: 403 }));
    renderAt('/evaluation');
    await waitFor(() => expectState('unauthorized', { text: /permission/i }));
  });

  it('a contract violation is unavailable, never partial data', async () => {
    fetchEvaluation.mockRejectedValue(new ApiError({ kind: 'contract', status: 200 }));
    renderAt('/evaluation');
    await waitFor(() => expectState('unavailable', { text: /./ }));
    expect(screen.queryByTestId('outcome-headline')).not.toBeInTheDocument();
  });

  it('an unknown report id is "not found"', async () => {
    fetchEvaluation.mockRejectedValue(new ApiError({ kind: 'not_found', status: 404 }));
    renderAt('/evaluation/nope');
    await waitFor(() => expect(screen.getByText('Not found')).toBeInTheDocument());
  });

  it('with several reports, lists links in the backend order (no re-sorting)', async () => {
    const list = clone(CAPTURED_LIST);
    list.evaluations = [
      { ...list.evaluations[0], evaluation_id: 'zzz_second_listed' },
      { ...list.evaluations[0], evaluation_id: 'aaa_first_alphabetically' },
    ];
    fetchEvaluations.mockResolvedValue(list);
    renderAt('/evaluation');
    const nav = await screen.findByRole('navigation', { name: 'Evaluation reports' });
    expect([...nav.querySelectorAll('a')].map((a) => a.textContent?.replace(/\s*\(.*\)$/, ''))).toEqual(['zzz_second_listed', 'aaa_first_alphabetically']);
    expect(fetchEvaluation).toHaveBeenCalledWith('zzz_second_listed', expect.anything());
  });

  it('is switched off by VITE_EVALUATION_VIEW=off and makes no request', () => {
    vi.stubEnv('VITE_EVALUATION_VIEW', 'off');
    renderAt('/evaluation');
    expect(screen.getByTestId('evaluation-disabled')).toBeInTheDocument();
    expect(fetchEvaluations).not.toHaveBeenCalled();
  });
});
