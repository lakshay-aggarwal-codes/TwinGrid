import '@/test/resizeObserver';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/apiError';
import { CAPTURED_EMPTY, CAPTURED_GAPS, CAPTURED_SAMPLES_ANY, clone } from '@/telemetry/history/testFixtures';

const { fetchFacilityId, fetchTelemetrySamples, fetchTelemetryGaps } = vi.hoisted(() => ({
  fetchFacilityId: vi.fn(),
  fetchTelemetrySamples: vi.fn(),
  fetchTelemetryGaps: vi.fn(),
}));
vi.mock('@/api/apiClient', () => ({ fetchFacilityId, fetchTelemetrySamples, fetchTelemetryGaps }));
vi.mock('@/lib/errorReporter.ts', () => ({ reportError: vi.fn() }));

import TelemetryHistory from '@/pages/TelemetryHistory.tsx';

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TelemetryHistory />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  fetchFacilityId.mockReset().mockResolvedValue(1);
  fetchTelemetrySamples.mockReset().mockResolvedValue(clone(CAPTURED_SAMPLES_ANY));
  fetchTelemetryGaps.mockReset().mockResolvedValue(clone(CAPTURED_GAPS));
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe('Telemetry history page', () => {
  it('requests the facility-derived sensor id, the live stream window, and shows stored samples with their origin', async () => {
    renderPage();
    expect(await screen.findByTestId('history-view')).toHaveAttribute('data-sensor-id', 'fac1.it_power_kw');
    expect(fetchTelemetrySamples).toHaveBeenCalledTimes(1);
    const [id, params] = fetchTelemetrySamples.mock.calls[0];
    expect(id).toBe('fac1.it_power_kw');
    expect(params.from).toMatch(/Z$/);
    expect(params.to).toMatch(/Z$/);
    expect(params.limit).toBe(5000);
    expect(Date.parse(params.to) - Date.parse(params.from)).toBe(24 * 3_600_000);
    expect(document.querySelector('[data-provenance-badge="simulated"]')).not.toBeNull();
    expect(screen.getAllByText(/not the live value/).length).toBeGreaterThan(0);
  });

  it('an empty window is "No stored telemetry for this window", never a flat chart', async () => {
    fetchTelemetrySamples.mockResolvedValue(clone(CAPTURED_EMPTY));
    fetchTelemetryGaps.mockResolvedValue({ ...clone(CAPTURED_GAPS), gaps: [] });
    renderPage();
    expect(await screen.findByText('No stored telemetry for this window.')).toBeInTheDocument();
    expect(screen.queryByTestId('history-chart')).toBeNull();
  });

  it('404 Unknown sensor is "Sensor not registered on this backend", not an empty chart', async () => {
    fetchTelemetrySamples.mockRejectedValue(new ApiError({ kind: 'not_found', status: 404 }));
    renderPage();
    expect(await screen.findByText('Sensor not registered on this backend.')).toBeInTheDocument();
    expect(screen.queryByTestId('history-chart')).toBeNull();
    expect(screen.queryByText('No stored telemetry for this window.')).toBeNull();
  });

  it('changing the measurand loads that sensor; refresh re-requests; there is no timer', async () => {
    renderPage();
    await screen.findByTestId('history-view');
    fireEvent.change(screen.getByLabelText('Measurand'), { target: { value: 'humidity_pct' } });
    await waitFor(() => expect(fetchTelemetrySamples.mock.calls.at(-1)?.[0]).toBe('fac1.humidity_pct'));
    expect(screen.getByLabelText('Window')).toHaveValue('24');
  });

  it('a facility failure is an error state, and no sensor is guessed', async () => {
    fetchFacilityId.mockRejectedValue(new ApiError({ kind: 'server', status: 500 }));
    renderPage();
    await waitFor(() => expect(document.querySelector('[data-state="error"]')).not.toBeNull());
    expect(fetchTelemetrySamples).not.toHaveBeenCalled();
  });

  it('is replaced by a plain notice when switched off at build time', async () => {
    vi.stubEnv('VITE_TELEMETRY_HISTORY', 'off');
    renderPage();
    expect(await screen.findByTestId('telemetry-history-disabled')).toBeInTheDocument();
    expect(fetchFacilityId).not.toHaveBeenCalled();
  });
});
