import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CAPTURED_REGISTRY, clone as cloneRegistry } from '@/scenarios/testFixtures';
import { COMPLETED, RESULT, clone } from '@/runs/testFixtures';

const { fetchRun, fetchRunResult, fetchScenarios } = vi.hoisted(() => ({ fetchRun: vi.fn(), fetchRunResult: vi.fn(), fetchScenarios: vi.fn() }));
vi.mock('@/api/apiClient', () => ({ fetchRun, fetchRunResult, fetchScenarios, submitRun: vi.fn(), fetchScenarioWhatIf: vi.fn(), fetchWhatIf: vi.fn() }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import Runs from './Runs.tsx';

const renderAt = (path: string) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Runs />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  localStorage.clear();
  fetchRun.mockReset().mockResolvedValue(clone(COMPLETED));
  fetchRunResult.mockReset().mockResolvedValue(clone(RESULT));
  fetchScenarios.mockReset().mockResolvedValue(cloneRegistry(CAPTURED_REGISTRY));
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe('Runs page', () => {
  it('/runs/:id recovers the run from the URL alone', async () => {
    renderAt(`/runs/${COMPLETED.run_id}`);
    expect(await screen.findByTestId('run-result')).toBeInTheDocument();
    expect(fetchRun.mock.calls[0][0]).toBe(COMPLETED.run_id);
    expect(fetchRunResult.mock.calls[0][0]).toBe(COMPLETED.run_id);
    expect(document.title).toBe('TwinGrid — Run');
    expect(fetchScenarios).not.toHaveBeenCalled();
  });

  it('/runs offers select, configure and submit', async () => {
    renderAt('/runs');
    expect(await screen.findByTestId('run-start')).toBeInTheDocument();
    expect(fetchRun).not.toHaveBeenCalled();
    expect(document.title).toBe('TwinGrid — New run');
  });

  it('the rollback flag turns the workflow off without fetching anything', async () => {
    vi.stubEnv('VITE_RUN_WORKFLOW', 'off');
    renderAt(`/runs/${COMPLETED.run_id}`);
    await waitFor(() => expect(screen.getByTestId('runs-disabled')).toBeInTheDocument());
    expect(fetchRun).not.toHaveBeenCalled();
    expect(fetchScenarios).not.toHaveBeenCalled();
  });
});
