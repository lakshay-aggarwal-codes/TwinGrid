import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { COMPLETED, FAILED_FORCED, QUEUED, RESULT, clone } from '@/runs/testFixtures';

const { fetchRun, fetchRunResult } = vi.hoisted(() => ({ fetchRun: vi.fn(), fetchRunResult: vi.fn() }));
vi.mock('@/api/apiClient', () => ({ fetchRun, fetchRunResult, submitRun: vi.fn(), fetchWhatIf: vi.fn(), fetchScenarios: vi.fn(), fetchScenarioWhatIf: vi.fn() }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { RunMonitor } from './RunMonitor';

const ID = QUEUED.run_id;
const RUNNING = { ...clone(QUEUED), status: 'running', started_at: '2026-10-09T18:53:00.296111+00:00' };

/** React Query schedules with timers, so every step moves the fake clock; nothing here waits on real time. */
const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

const renderMonitor = (id = ID) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RunMonitor id={id} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const statusText = () => screen.getByTestId('run-status-text').textContent;

beforeEach(() => {
  vi.useFakeTimers();
  fetchRun.mockReset();
  fetchRunResult.mockReset().mockResolvedValue(clone(RESULT));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('RunMonitor polling state machine', () => {
  it('polls queued -> running -> completed with backoff, fetches the result only after completed, then stops polling', async () => {
    fetchRun.mockResolvedValueOnce(clone(QUEUED)).mockResolvedValueOnce(clone(QUEUED)).mockResolvedValueOnce(clone(RUNNING)).mockResolvedValue(clone(COMPLETED));
    renderMonitor();

    await advance(1);
    expect(fetchRun).toHaveBeenCalledTimes(1);
    expect(fetchRun.mock.calls[0][0]).toBe(ID);
    expect(fetchRun.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    expect(statusText()).toBe('Queued');

    await advance(400); // t ~ 400 ms: the first wait is 500 ms
    expect(fetchRun).toHaveBeenCalledTimes(1);
    await advance(200); // t ~ 600 ms
    expect(fetchRun).toHaveBeenCalledTimes(2);
    expect(statusText()).toBe('Queued');

    await advance(800); // second wait is 800 ms: t ~ 1400 ms
    expect(fetchRun).toHaveBeenCalledTimes(3);
    expect(statusText()).toBe('Running');
    // A submitted job is not a result: nothing was requested and nothing is shown.
    expect(fetchRunResult).not.toHaveBeenCalled();
    expect(screen.queryByTestId('run-result')).toBeNull();

    await advance(1300); // third wait is 1280 ms: t ~ 2700 ms
    expect(fetchRun).toHaveBeenCalledTimes(4);
    expect(statusText()).toBe('Completed');
    expect(fetchRunResult).toHaveBeenCalledTimes(1);
    expect(fetchRunResult.mock.calls[0][0]).toBe(ID);
    expect(screen.getByTestId('run-result')).toBeInTheDocument();

    await advance(30_000);
    expect(fetchRun).toHaveBeenCalledTimes(4); // a final status is never polled again
    expect(fetchRunResult).toHaveBeenCalledTimes(1);
  });

  it('a completed status whose result has not arrived renders no result panel', async () => {
    fetchRun.mockResolvedValue(clone(COMPLETED));
    fetchRunResult.mockReturnValue(new Promise(() => {}));
    renderMonitor();
    await advance(50);
    expect(statusText()).toBe('Completed');
    expect(screen.getByText('Fetching the result…')).toBeInTheDocument();
    expect(screen.queryByTestId('run-result')).toBeNull();
  });

  it('a completed status whose result fetch fails renders no result panel', async () => {
    fetchRun.mockResolvedValue(clone(COMPLETED));
    fetchRunResult.mockRejectedValue(new ApiError({ kind: 'conflict', status: 409 }));
    renderMonitor();
    await advance(50);
    expect(statusText()).toBe('Completed');
    expect(screen.queryByTestId('run-result')).toBeNull();
    expect(screen.getByTestId('run-monitor').querySelector('[data-state="error"]')).not.toBeNull();
  });

  it('a result that names another run is not shown', async () => {
    fetchRun.mockResolvedValue(clone(COMPLETED));
    fetchRunResult.mockResolvedValue({ ...clone(RESULT), run_id: '00000000-0000-0000-0000-000000000001' });
    renderMonitor();
    await advance(50);
    expect(screen.queryByTestId('run-result')).toBeNull();
    expect(screen.getByText(/does not belong to this run/)).toBeInTheDocument();
  });

  it('a status record for another run is not shown and requests no result', async () => {
    fetchRun.mockResolvedValue({ ...clone(COMPLETED), run_id: '00000000-0000-0000-0000-000000000002' });
    renderMonitor();
    await advance(50);
    expect(screen.queryByTestId('run-status')).toBeNull();
    expect(screen.queryByTestId('run-result')).toBeNull();
    expect(fetchRunResult).not.toHaveBeenCalled();
    expect(screen.getByText(/does not belong to this run/)).toBeInTheDocument();
  });

  it('reload recovery: the run id alone (from the URL) restores status and result', async () => {
    fetchRun.mockResolvedValue(clone(COMPLETED));
    renderMonitor(COMPLETED.run_id);
    await advance(50);
    expect(screen.getByTestId('run-id')).toHaveTextContent(COMPLETED.run_id);
    expect(statusText()).toBe('Completed');
    const result = screen.getByTestId('run-result');
    expect(result.querySelector('[data-provenance-run]')).toHaveTextContent(`Run ${RESULT.run_id}`);
    expect(result.querySelector('[data-provenance-scenario]')).toHaveTextContent(`Scenario ${RESULT.scenario_id}`);
    expect(result.querySelector('[data-provenance-badge="simulated"]')).not.toBeNull();
    expect(screen.getByTestId('run-result-weather-plant')).toHaveTextContent('Constant-input weather, simulated plant');
    expect(screen.getByTestId('run-fallback-carbon')).toBeInTheDocument();
    expect(screen.getByTestId('run-result-parameters')).toHaveTextContent('outside_temp 38');
    expect(screen.queryByText(/Reference weather/)).toBeNull();
  });

  it('shows elapsed figures only as differences between backend timestamps', async () => {
    fetchRun.mockResolvedValue(clone(COMPLETED));
    renderMonitor(COMPLETED.run_id);
    await advance(50);
    expect(screen.getByTestId('run-status').querySelector('[data-duration-row="ran"]')).toHaveTextContent('5 ms');
    expect(screen.getByTestId('run-status').querySelector('[data-time-row="created"]')).toHaveTextContent('2026-10-09 18:53:00 UTC');
  });
});

describe('RunMonitor statuses', () => {
  it('queued says no worker has started it and offers no result', async () => {
    fetchRun.mockResolvedValue(clone(QUEUED));
    renderMonitor();
    await advance(1);
    expect(screen.getByText(/No worker has started it yet/)).toBeInTheDocument();
    expect(screen.getByTestId('run-status')).toHaveTextContent('Not started yet');
    expect(screen.getByTestId('run-status-announcement')).toHaveTextContent('Run status: Queued');
  });

  it('failed shows the backend code as fixed copy, no result, and stops polling', async () => {
    fetchRun.mockResolvedValue(clone(FAILED_FORCED));
    renderMonitor(FAILED_FORCED.run_id);
    await advance(50);
    expect(statusText()).toBe('Failed');
    expect(screen.getByTestId('run-failure')).toHaveTextContent('The run failed inside the backend.');
    expect(screen.getByTestId('run-status')).not.toHaveTextContent('internal_error');
    expect(screen.queryByTestId('run-result')).toBeNull();
    await advance(20_000);
    expect(fetchRun).toHaveBeenCalledTimes(1);
    expect(fetchRunResult).not.toHaveBeenCalled();
  });

  it('an unknown failure code is said not to be recognised, never echoed', async () => {
    fetchRun.mockResolvedValue({ ...clone(FAILED_FORCED), failure_code: 'segfault' });
    renderMonitor(FAILED_FORCED.run_id);
    await advance(50);
    expect(screen.getByTestId('run-failure')).toHaveTextContent('not recognised');
    expect(screen.getByTestId('run-failure')).not.toHaveTextContent('segfault');
  });

  it('cancelled is distinct from failed: no failure line, no result', async () => {
    fetchRun.mockResolvedValue({ ...clone(QUEUED), status: 'cancelled' });
    renderMonitor();
    await advance(50);
    expect(statusText()).toBe('Cancelled');
    expect(screen.getByText(/stopped before it finished/)).toBeInTheDocument();
    expect(screen.queryByTestId('run-failure')).toBeNull();
    expect(screen.queryByTestId('run-result')).toBeNull();
    await advance(20_000);
    expect(fetchRun).toHaveBeenCalledTimes(1);
  });

  it('an unrecognised status is labelled, stops polling, and can be checked again by hand', async () => {
    fetchRun.mockResolvedValue({ ...clone(QUEUED), status: 'archived' });
    renderMonitor();
    await advance(50);
    expect(statusText()).toBe('Unrecognised status');
    expect(screen.getByTestId('run-status')).toHaveAttribute('data-run-status', 'unrecognised');
    expect(screen.queryByTestId('run-result')).toBeNull();
    await advance(20_000);
    expect(fetchRun).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    await advance(50);
    expect(fetchRun).toHaveBeenCalledTimes(2);
  });

  it.each(['queued', 'running', 'completed', 'failed', 'cancelled', 'archived'])('no progress bar is ever rendered (%s)', async (status) => {
    fetchRun.mockResolvedValue({ ...clone(QUEUED), status });
    renderMonitor();
    await advance(50);
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getByTestId('run-monitor').querySelector('[role="progressbar"],progress')).toBeNull();
  });

  it('a transient network failure is waited out and polling resumes', async () => {
    fetchRun.mockRejectedValueOnce(new ApiError({ kind: 'network' })).mockResolvedValue(clone(QUEUED));
    renderMonitor();
    await advance(50);
    expect(screen.getByTestId('run-monitor').querySelector('[data-state="error"]')).not.toBeNull();
    expect(screen.queryByTestId('run-status')).toBeNull();
    await advance(600);
    expect(fetchRun).toHaveBeenCalledTimes(2);
    expect(statusText()).toBe('Queued');
  });

  it('an expired or unknown run (404) is an explicit state and is not polled', async () => {
    fetchRun.mockRejectedValue(new ApiError({ kind: 'not_found', status: 404 }));
    renderMonitor();
    await advance(50);
    expect(within(screen.getByTestId('run-monitor')).getByText('Not found')).toBeInTheDocument();
    await advance(30_000);
    expect(fetchRun).toHaveBeenCalledTimes(1);
  });
});
