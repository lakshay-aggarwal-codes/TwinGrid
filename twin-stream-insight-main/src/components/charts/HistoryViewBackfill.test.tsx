import '@/test/resizeObserver';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { BackfillState } from '@/features/realtime-resilience/backfill';
import { requestWindow } from '@/telemetry/history/model';
import { SYNTHETIC_SAMPLE } from '@/telemetry/history/testFixtures';
import type { HistoryData } from '@/telemetry/history/useTelemetryHistory';
import { HistoryView } from './HistoryView';

afterEach(cleanup);

const SENSOR = 'fac1.it_power_kw';
const end = Date.UTC(2026, 2, 1, 13, 0, 0);
const win = requestWindow(end, 2);
const at = (min: number) => new Date(Date.UTC(2026, 2, 1, 12, min, 0)).toISOString().replace(/\.\d{3}Z$/, 'Z');
const data = (): HistoryData => ({
  sensorId: SENSOR,
  unit: 'kW',
  samplingIntervalS: 300,
  thresholdS: 450,
  items: [SYNTHETIC_SAMPLE(at(0), 1), SYNTHETIC_SAMPLE(at(10), 2)],
  gaps: [],
  gapsTruncated: false,
  moreAvailable: false,
  pagesLoaded: 1,
});
const done = (missed: number, unit: string | null = 'kW'): BackfillState => ({
  status: 'done',
  window: { from: at(1), to: at(9), missedFrames: missed, truncated: false },
  series: [{ measurand: 'it_power_kw', sensorId: SENSOR, unit, samples: [SYNTHETIC_SAMPLE(at(4), 3), SYNTHETIC_SAMPLE(at(5), 4)] }],
  recovered: 2,
  moreAvailable: false,
});
const note = (id: string) => document.querySelector(`[data-note="${id}"]`);

describe('HistoryView with backfilled samples', () => {
  it('includes recovered samples and says so', () => {
    render(<HistoryView data={data()} window={win} backfill={done(2)} />);
    expect(note('backfill-merged')?.textContent).toMatch(/2 samples recovered/);
    expect(screen.getByTestId('history-facts').textContent).toMatch(/4 samples loaded/);
    expect(note('backfill-shortfall')).toBeNull();
  });

  it('a shortfall is shown as a gap notice, not filled', () => {
    render(<HistoryView data={data()} window={win} backfill={done(6)} />);
    expect(note('backfill-shortfall')?.textContent).toMatch(/missed 6 frames.*only 2 valid samples/);
  });

  it('a wrong unit is refused with a notice', () => {
    render(<HistoryView data={data()} window={win} backfill={done(2, 'W')} />);
    expect(note('backfill-unit')).not.toBeNull();
    expect(note('backfill-merged')).toBeNull();
    expect(screen.getByTestId('history-facts').textContent).toMatch(/2 samples loaded/);
  });

  it('unavailable backfill says the window is not filled', () => {
    render(<HistoryView data={data()} window={win} backfill={{ status: 'unavailable', window: { from: at(1), to: at(9), missedFrames: 3, truncated: false } }} />);
    expect(note('backfill-unavailable')).not.toBeNull();
  });

  it('states the gap granularity of the backend rule', () => {
    render(<HistoryView data={data()} window={win} />);
    expect(note('gap-granularity')?.textContent).toMatch(/shorter than 450 s \(7\.5 min\)/);
  });
});
