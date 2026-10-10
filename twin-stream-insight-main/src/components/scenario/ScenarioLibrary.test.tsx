import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { CAPTURED_REGISTRY, clone } from '@/scenarios/testFixtures';
import { SELECTION_KEY } from '@/scenarios/selection';
import { whatIf } from '@/test/whatifFixtures.ts';

const { fetchScenarios, fetchScenarioWhatIf, fetchWhatIf } = vi.hoisted(() => ({ fetchScenarios: vi.fn(), fetchScenarioWhatIf: vi.fn(), fetchWhatIf: vi.fn() }));
vi.mock('@/api/apiClient', () => ({ fetchScenarios, fetchScenarioWhatIf, fetchWhatIf }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import { ScenarioLibrary } from './ScenarioLibrary';

const inputs = { utilisation: 0.65, outside_temp_C: 38, water_stress: 0, mode: 'auto', chilled_water_temp_C: 7 };
const result = (id: string, over: Record<string, unknown> = {}) => ({ ...whatIf(), inputs, scenario_id: id, ...over }) as never;

const renderLibrary = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <ScenarioLibrary />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  localStorage.clear();
  fetchScenarios.mockReset().mockResolvedValue(clone(CAPTURED_REGISTRY));
  fetchScenarioWhatIf.mockReset().mockImplementation((p: { scenario_id: string }) => Promise.resolve(result(p.scenario_id)));
});
afterEach(() => vi.unstubAllEnvs());

describe('ScenarioLibrary', () => {
  it('lists the backend descriptors (no hardcoded list) with a weather/plant line computed from the descriptor fields', async () => {
    renderLibrary();
    const picker = await screen.findByTestId('scenario-picker');
    const options = picker.querySelectorAll('[data-scenario-option]');
    expect([...options].map((o) => o.getAttribute('data-scenario-option'))).toEqual(CAPTURED_REGISTRY.scenarios.map((s) => s.id));
    expect(within(picker).getByRole('radio', { name: 'Heat wave' })).toBeInTheDocument();
    expect(picker.querySelectorAll('[data-scenario-weather-plant]')[0]).toHaveTextContent('Constant-input weather, simulated plant');
    // The backend says constant_input, so the app must never claim reference weather.
    expect(screen.queryByText(/Reference weather/)).toBeNull();
  });

  it('an unsupported scenario type is labelled, in the unsupported_scenario state, and cannot be selected', async () => {
    const body = clone(CAPTURED_REGISTRY);
    body.scenarios[1].kind = 'carbon-shock';
    fetchScenarios.mockResolvedValue(body);
    renderLibrary();
    const option = (await screen.findByTestId('scenario-picker')).querySelector('[data-scenario-option="whatif-peak-workload"]') as HTMLElement;
    expect(within(option).getByText('Unsupported scenario type')).toBeInTheDocument();
    expect(option.querySelector('[data-state="unsupported_scenario"]')).not.toBeNull();
    expect(within(option).getByRole('radio')).toBeDisabled();
  });

  it('nothing runs on selection; "Preview scenario" sends the scenario id and the id appears in the strip', async () => {
    renderLibrary();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    expect(screen.getByText(/Nothing has been run yet/)).toBeInTheDocument();
    expect(fetchScenarioWhatIf).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Preview scenario' }));
    const resultBlock = await screen.findByTestId('scenario-result');
    expect(fetchScenarioWhatIf).toHaveBeenCalledTimes(1);
    expect(fetchScenarioWhatIf.mock.calls[0][0]).toEqual({ scenario_id: 'whatif-heat-wave' });
    expect(fetchScenarioWhatIf.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    expect(resultBlock.querySelector('[data-provenance-scenario]')).toHaveTextContent('Scenario whatif-heat-wave');
    expect(resultBlock.querySelector('[data-provenance-preview]')).not.toBeNull();
    expect(resultBlock.querySelector('[data-provenance-badge="unverified"]')).not.toBeNull();
    expect(screen.getByTestId('scenario-fallback-carbon')).toBeInTheDocument();
    expect(screen.getByTestId('scenario-inputs')).toHaveTextContent('outside 38 °C');
  });

  it('an edited parameter is sent as an explicit override under the backend name', async () => {
    renderLibrary();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.change(screen.getByLabelText(/Outside temp/), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview scenario' }));
    await screen.findByTestId('scenario-result');
    expect(fetchScenarioWhatIf.mock.calls[0][0]).toEqual({ scenario_id: 'whatif-heat-wave', outside_temp: 30 });
  });

  it('an out-of-bounds value shows the backend bound and blocks the request', async () => {
    renderLibrary();
    fireEvent.click(await screen.findByRole('radio', { name: 'Heat wave' }));
    fireEvent.change(screen.getByLabelText(/Outside temp/), { target: { value: '99' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Must be at most 50');
    expect(screen.getByRole('button', { name: 'Preview scenario' })).toBeDisabled();
  });

  it('the selection is remembered by id and restored after a reload', async () => {
    const first = renderLibrary();
    fireEvent.click(await screen.findByRole('radio', { name: 'Drought' }));
    expect(localStorage.getItem(SELECTION_KEY)).toBe('whatif-drought');
    first.unmount();

    renderLibrary();
    expect(await screen.findByRole('radio', { name: 'Drought' })).toBeChecked();
    expect(screen.getByTestId('scenario-review')).toHaveTextContent('Scenario id: whatif-drought');
  });

  it('a remembered id the backend no longer lists is reported, not replaced', async () => {
    localStorage.setItem(SELECTION_KEY, 'retired-scenario');
    renderLibrary();
    await screen.findByTestId('scenario-picker');
    expect(screen.getByText(/no longer listed/)).toBeInTheDocument();
    for (const r of screen.getAllByRole('radio')) expect(r).not.toBeChecked();
  });

  it('a registry failure is an explicit error state, not an empty list', async () => {
    fetchScenarios.mockRejectedValue(new ApiError({ kind: 'network' }));
    renderLibrary();
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByTestId('scenario-picker')).toBeNull();
  });

  it('an empty registry says so', async () => {
    fetchScenarios.mockResolvedValue({ registry_version: '1', scenarios: [] });
    renderLibrary();
    expect(await screen.findByText('The backend lists no scenarios.')).toBeInTheDocument();
  });

  it('a preview whose request is rejected shows the failure and keeps the library usable', async () => {
    fetchScenarioWhatIf.mockRejectedValue(new ApiError({ kind: 'contract' }));
    renderLibrary();
    fireEvent.click(await screen.findByRole('radio', { name: 'Baseline' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview scenario' }));
    await waitFor(() => expect(screen.getByTestId('scenario-library').querySelector('[data-state="unavailable"]')).not.toBeNull());
    expect(screen.queryByTestId('scenario-result')).toBeNull();
  });

  it('renders nothing when the rollback flag is off, and does not fetch', () => {
    vi.stubEnv('VITE_SCENARIO_LIBRARY', 'off');
    const { container } = renderLibrary();
    expect(container).toBeEmptyDOMElement();
    expect(fetchScenarios).not.toHaveBeenCalled();
  });
});
