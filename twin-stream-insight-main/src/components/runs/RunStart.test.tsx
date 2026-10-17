import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { CAPTURED_REGISTRY, clone } from '@/scenarios/testFixtures';
import { SELECTION_KEY } from '@/scenarios/selection';
import { SUBMIT } from '@/runs/testFixtures';

const { fetchScenarios, submitRun } = vi.hoisted(() => ({ fetchScenarios: vi.fn(), submitRun: vi.fn() }));
vi.mock('@/api/apiClient', () => ({ fetchScenarios, submitRun, fetchScenarioWhatIf: vi.fn(), fetchWhatIf: vi.fn(), fetchRun: vi.fn(), fetchRunResult: vi.fn() }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { RunStart } from './RunStart';

const RunPage = () => <div data-testid="run-page">{useParams().id}</div>;

const renderStart = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/runs']}>
        <Routes>
          <Route path="/runs" element={<RunStart />} />
          <Route path="/runs/:id" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const submitButton = () => screen.getByRole('button', { name: /Submit simulation run|Submitting/ });
const heatWaveId = CAPTURED_REGISTRY.scenarios.find((s) => s.label === 'Heat wave')!.id;

beforeEach(() => {
  localStorage.clear();
  fetchScenarios.mockReset().mockResolvedValue(clone(CAPTURED_REGISTRY));
  submitRun.mockReset().mockResolvedValue(clone(SUBMIT));
});
afterEach(() => cleanup());

describe('RunStart', () => {
  it('lists the backend scenarios; selecting one submits nothing', async () => {
    renderStart();
    const picker = await screen.findByTestId('scenario-picker');
    expect(picker.querySelectorAll('[data-scenario-option]')).toHaveLength(CAPTURED_REGISTRY.scenarios.length);
    fireEvent.click(screen.getByRole('radio', { name: 'Heat wave' }));
    expect(submitRun).not.toHaveBeenCalled();
    expect(screen.getByTestId('run-review')).toHaveTextContent(`Scenario id: ${heatWaveId}`);
    expect(screen.getByTestId('run-review')).toHaveTextContent('Constant-input weather, simulated plant');
    expect(localStorage.getItem(SELECTION_KEY)).toBe(heatWaveId);
  });

  it('there is no submit control until a scenario is chosen', async () => {
    renderStart();
    await screen.findByTestId('scenario-picker');
    expect(screen.queryByRole('button', { name: /Submit simulation run/ })).toBeNull();
  });

  it('submits the scenario id alone when nothing was overridden, then goes to the run (not to a result)', async () => {
    renderStart();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.click(submitButton());
    expect(await screen.findByTestId('run-page')).toHaveTextContent(SUBMIT.run_id);
    expect(submitRun).toHaveBeenCalledTimes(1);
    expect(submitRun.mock.calls[0][0]).toEqual({ scenario_id: heatWaveId });
    expect(screen.queryByTestId('run-result')).toBeNull();
  });

  it('an edited parameter is sent under `parameters` with its backend name', async () => {
    renderStart();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.change(screen.getByLabelText(/Outside temp/), { target: { value: '30' } });
    fireEvent.click(submitButton());
    await screen.findByTestId('run-page');
    expect(submitRun.mock.calls[0][0]).toEqual({ scenario_id: heatWaveId, parameters: { outside_temp: 30 } });
  });

  it('double submit is guarded: disabled while submitting, one request for two clicks, no backend status invented', async () => {
    let resolve!: (v: unknown) => void;
    submitRun.mockReturnValue(new Promise((r) => (resolve = r)));
    renderStart();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    const button = submitButton();
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(submitButton()).toBeDisabled());
    expect(submitButton()).toHaveTextContent('Submitting…');
    expect(screen.getByTestId('run-submitting')).toHaveTextContent('has not accepted this run yet');
    expect(screen.queryByTestId('run-status')).toBeNull();
    expect(submitRun).toHaveBeenCalledTimes(1);

    resolve(clone(SUBMIT));
    expect(await screen.findByTestId('run-page')).toHaveTextContent(SUBMIT.run_id);
    expect(submitRun).toHaveBeenCalledTimes(1);
  });

  it('a rejected submit is an explicit error, keeps the form, and allows trying again', async () => {
    submitRun.mockRejectedValueOnce(new ApiError({ kind: 'unavailable', status: 503 }));
    renderStart();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.click(submitButton());
    expect(await screen.findByText('Service unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('run-page')).toBeNull();
    await waitFor(() => expect(submitButton()).not.toBeDisabled());
    fireEvent.click(submitButton());
    expect(await screen.findByTestId('run-page')).toBeInTheDocument();
    expect(submitRun).toHaveBeenCalledTimes(2);
  });

  it('an out-of-bounds value shows the backend bound and blocks submit', async () => {
    renderStart();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.change(screen.getByLabelText(/Outside temp/), { target: { value: '99' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Must be at most 50');
    expect(submitButton()).toBeDisabled();
    fireEvent.click(submitButton());
    expect(submitRun).not.toHaveBeenCalled();
  });

  it('an unsupported scenario type cannot be selected', async () => {
    const body = clone(CAPTURED_REGISTRY);
    body.scenarios[1].kind = 'carbon-shock';
    fetchScenarios.mockResolvedValue(body);
    renderStart();
    const option = (await screen.findByTestId('scenario-picker')).querySelector(`[data-scenario-option="${body.scenarios[1].id}"]`) as HTMLElement;
    expect(option.querySelector('input[type="radio"]')).toBeDisabled();
    expect(option.querySelector('[data-state="unsupported_scenario"]')).not.toBeNull();
  });

  it('a registry failure is an explicit error and shows no form', async () => {
    fetchScenarios.mockRejectedValue(new ApiError({ kind: 'network' }));
    renderStart();
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByTestId('run-start')).toBeNull();
  });
});
