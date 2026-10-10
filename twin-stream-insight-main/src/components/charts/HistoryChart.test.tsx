import '@/test/resizeObserver';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { buildChartModel, buildSeries, requestWindow } from '@/telemetry/history/model';
import type { HistoryData } from '@/telemetry/history/useTelemetryHistory';
import { CAPTURED_GAPS, CAPTURED_REPLAY, CAPTURED_SAMPLES_ANY, SENSOR_ID, SYNTHETIC_SAMPLE, clone } from '@/telemetry/history/testFixtures';
import { DOT_LIMIT, HistoryPlot, MAX_EXCLUDED_MARKS } from './HistoryChart';
import { HistoryLegend } from './HistoryLegend';
import { HistoryTable, TABLE_PAGE_SIZE } from './HistoryTable';
import { HistoryView } from './HistoryView';

afterEach(cleanup);

const domain: [number, number] = [Date.UTC(2026, 2, 1, 11, 30), Date.UTC(2026, 2, 1, 13, 30)];
const modelOf = (items = CAPTURED_SAMPLES_ANY.items, gaps = CAPTURED_GAPS.gaps) => {
  const { series } = buildSeries({ sensorId: SENSOR_ID, unit: 'kW', items, gaps });
  return { series, model: buildChartModel(series, gaps) };
};
const dataOf = (over: Partial<HistoryData> = {}): HistoryData => ({
  sensorId: SENSOR_ID,
  unit: 'kW',
  samplingIntervalS: 300,
  thresholdS: 450,
  items: clone(CAPTURED_SAMPLES_ANY.items),
  gaps: clone(CAPTURED_GAPS.gaps),
  gapsTruncated: false,
  moreAvailable: false,
  pagesLoaded: 1,
  ...over,
});
const win = requestWindow(domain[1], 2);

describe('HistoryPlot', () => {
  it('draws the captured series as two line segments with the reported gap between them', () => {
    const { model } = modelOf();
    const { container } = render(<HistoryPlot model={model} unit="kW" domain={domain} width={700} height={280} />);
    const path = container.querySelector('path.recharts-line-curve');
    expect(path).not.toBeNull();
    const d = path!.getAttribute('d') ?? '';
    expect((d.match(/M/g) ?? []).length).toBe(2); // broken at the gap: no line across the hole
    expect(container.querySelectorAll('.recharts-reference-area').length).toBe(1);
    expect(container.textContent).toContain('gap');
  });

  it('with no reported gap the same hole is NOT broken (the client never infers one)', () => {
    const { model } = modelOf(CAPTURED_SAMPLES_ANY.items, []);
    const { container } = render(<HistoryPlot model={model} unit="kW" domain={domain} width={700} height={280} />);
    const d = container.querySelector('path.recharts-line-curve')?.getAttribute('d') ?? '';
    expect((d.match(/M/g) ?? []).length).toBe(1);
    expect(container.querySelectorAll('.recharts-reference-area').length).toBe(0);
  });

  it('marks the invalid sample with a dashed vertical line and does not plot its value', () => {
    const { model } = modelOf();
    const { container } = render(<HistoryPlot model={model} unit="kW" domain={domain} width={700} height={280} />);
    const lines = container.querySelectorAll('.recharts-reference-line line');
    expect(lines.length).toBeGreaterThanOrEqual(1);
    expect(Array.from(lines).some((l) => l.getAttribute('stroke-dasharray') === '5 3')).toBe(true);
    expect(container.innerHTML).not.toContain('999999');
  });

  it('caps the markers drawn (all stay listed in the table)', () => {
    const many = Array.from({ length: MAX_EXCLUDED_MARKS + 50 }, (_, i) =>
      SYNTHETIC_SAMPLE(new Date(Date.UTC(2026, 2, 1, 12, 0, 0) + i * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'), 1, { quality: 'invalid', invalid_reason: 'range' }),
    );
    const { series, model } = modelOf([SYNTHETIC_SAMPLE('2026-03-01T11:59:00Z'), ...many], []);
    const { container } = render(<HistoryPlot model={model} unit="kW" domain={domain} width={700} height={280} />);
    expect(container.querySelectorAll('.recharts-reference-line').length).toBe(MAX_EXCLUDED_MARKS);
    expect(series.points.filter((p) => p.quality === 'invalid')).toHaveLength(MAX_EXCLUDED_MARKS + 50);
  });

  it('keeps every point of a large series on the line (no downsampling); only the per-point dots are dropped', () => {
    const n = DOT_LIMIT * 5;
    const items = Array.from({ length: n }, (_, i) => SYNTHETIC_SAMPLE(new Date(Date.UTC(2026, 2, 1, 12, 0, 0) + i * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'), i));
    const { model } = modelOf(items, []);
    expect(model.line).toHaveLength(n);
    const { container } = render(<HistoryPlot model={model} unit="kW" domain={domain} width={700} height={280} />);
    const d = container.querySelector('path.recharts-line-curve')?.getAttribute('d') ?? '';
    expect((d.match(/[ML]/g) ?? []).length).toBe(n);
    expect(container.querySelectorAll('.recharts-line-dot').length).toBe(0);
  });
});

describe('HistoryLegend', () => {
  it('names every mark in text, only for marks that exist', () => {
    const { model } = modelOf();
    render(<HistoryLegend model={model} />);
    const legend = screen.getByTestId('history-legend');
    expect(within(legend).getByText(/Valid sample/)).toBeInTheDocument();
    expect(within(legend).getByText(/Gap reported by the backend/)).toBeInTheDocument();
    expect(within(legend).getByText(/Invalid sample: not plotted/)).toBeInTheDocument();
    expect(within(legend).queryByText(/Unrecognised quality/)).toBeNull();
  });

  it('no gap and no invalid => only the line entry', () => {
    const { model } = modelOf(CAPTURED_REPLAY.items, []);
    render(<HistoryLegend model={model} />);
    expect(screen.getByTestId('history-legend').querySelectorAll('li')).toHaveLength(1);
  });
});

describe('HistoryTable (accessible alternative)', () => {
  it('lists every sample including the invalid one, with quality, origin and the backend reason', () => {
    const { series } = modelOf();
    render(<HistoryTable series={series} gaps={CAPTURED_GAPS.gaps} />);
    const rows = within(screen.getByTestId('history-table')).getAllByRole('row');
    const dataRows = rows.filter((r) => r.querySelector('td'));
    expect(dataRows.length).toBeGreaterThanOrEqual(CAPTURED_SAMPLES_ANY.items.length);
    const invalid = dataRows.find((r) => r.getAttribute('data-quality') === 'invalid')!;
    expect(invalid.textContent).toContain('Invalid');
    expect(invalid.textContent).toContain('range');
    expect(invalid.textContent).toContain('Simulated');
    expect(screen.getByTestId('history-gaps-table').textContent).toContain('1500');
  });

  it('pages a large series without dropping rows', () => {
    const n = TABLE_PAGE_SIZE * 2 + 5;
    const items = Array.from({ length: n }, (_, i) => SYNTHETIC_SAMPLE(new Date(Date.UTC(2026, 2, 1) + i * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z'), i));
    const { series } = modelOf(items, []);
    render(<HistoryTable series={series} gaps={[]} />);
    expect(screen.getByText(`Page 1 of 3 (${n} samples)`)).toBeInTheDocument();
  });
});

describe('HistoryView', () => {
  it('shows the simulated origin, the stored-not-live wording and the declared (not guaranteed) interval', () => {
    render(<HistoryView data={dataOf()} window={win} />);
    expect(document.querySelector('[data-provenance-badge="simulated"]')).not.toBeNull();
    expect(screen.getAllByText(/not the live value/).length).toBeGreaterThan(0);
    expect(screen.getByTestId('history-facts').textContent).toMatch(/declared, not a guarantee of spacing/);
    expect(screen.getByRole('img').getAttribute('aria-label')).toMatch(/1 backend-reported gaps/);
  });

  it('replay origin reads Replayed (not live), not Unverified', () => {
    render(<HistoryView data={dataOf({ items: clone(CAPTURED_REPLAY.items), gaps: [] })} window={win} />);
    expect(document.querySelector('[data-provenance-badge="replayed"]')).not.toBeNull();
    expect(document.querySelector('[data-provenance-badge="unverified"]')).toBeNull();
  });

  it('an unknown or absent origin reads Unverified source', () => {
    const items = [SYNTHETIC_SAMPLE('2026-03-01T12:00:00Z', 1, { origin: 'teleported' }), SYNTHETIC_SAMPLE('2026-03-01T12:05:00Z', 1, { origin: null })];
    render(<HistoryView data={dataOf({ items, gaps: [] })} window={win} />);
    expect(document.querySelector('[data-provenance-badge="unverified"]')).not.toBeNull();
    expect(document.querySelector('[data-note="mixed-origins"]')).not.toBeNull();
  });

  it('says when more stored data exists than was loaded, and when gaps were truncated', () => {
    render(<HistoryView data={dataOf({ moreAvailable: true, gapsTruncated: true, pagesLoaded: 4 })} window={win} />);
    expect(document.querySelector('[data-note="more-available"]')?.textContent).toMatch(/More stored samples exist/);
    expect(document.querySelector('[data-note="more-available"]')?.textContent).toMatch(/Nothing is downsampled/);
    expect(document.querySelector('[data-note="gaps-truncated"]')).not.toBeNull();
  });

  it('only invalid samples: explicit notice, no chart, still listed', () => {
    const items = [SYNTHETIC_SAMPLE('2026-03-01T12:00:00Z', 999999, { quality: 'invalid', invalid_reason: 'range' })];
    render(<HistoryView data={dataOf({ items, gaps: [] })} window={win} />);
    expect(screen.getByText('No valid samples')).toBeInTheDocument();
    expect(screen.queryByTestId('history-chart')).toBeNull();
  });
});
