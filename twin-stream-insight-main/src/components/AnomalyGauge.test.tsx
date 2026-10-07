import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AnomalyStatusPayload } from '@/api/apiClient';
import { AnomalyGauge } from './AnomalyGauge';
import { AnomalyAlert } from './AnomalyAlert';

const s = (over: Partial<AnomalyStatusPayload>): AnomalyStatusPayload => ({ status: 'ok', message: 'm', score: 0.004, threshold: 0.01, type: null, ...over });

const FAIL_CLOSED: Array<[string, AnomalyStatusPayload | null, RegExp]> = [
  ['unavailable', s({ status: 'unavailable', score: null, threshold: null }), /Detector unavailable/],
  ['error', s({ status: 'error', score: null, threshold: null }), /Detector error/],
  ['unknown', s({ status: 'recalibrating' }), /Unrecognised detector status/],
  ['none received', null, /Detector status not reported/],
];

describe('AnomalyGauge', () => {
  it.each(FAIL_CLOSED)('%s is shown as itself and never as normal / green / "No active alert"', (_n, status, label) => {
    const { container } = render(<AnomalyGauge status={status} />);
    expect(screen.getByTestId('anomaly-label')).toHaveTextContent(label);
    expect(container).not.toHaveTextContent(/NOMINAL|No anomaly flagged|No active alert|All clear|normal/i);
    expect(container.querySelector('.text-green-500, .text-success, [stroke="#22c55e"]')).toBeNull();
    expect(screen.queryByTestId('anomaly-readout')).toBeNull();
    expect(container).not.toHaveTextContent(/%|score \d/);
    expect(container.querySelector('.anomaly-flash-border')).toBeNull();
  });

  it('warming up shows n/window and no number', () => {
    const { container } = render(<AnomalyGauge status={s({ status: 'warming_up', score: null, threshold: null, window_filled: 3, window_size: 12 })} />);
    expect(screen.getByTestId('anomaly-label')).toHaveTextContent('Warming up (3/12)');
    expect(screen.queryByTestId('anomaly-readout')).toBeNull();
    expect(container).not.toHaveTextContent(/\b0\b/);
  });

  it('ok shows score beside the backend threshold with a marker, and no %', () => {
    const { container } = render(<AnomalyGauge status={s({ status: 'ok', score: 0.0123, threshold: 0.01 })} />);
    expect(screen.getByTestId('anomaly-readout')).toHaveTextContent('score 0.0123 / threshold 0.0100');
    expect(screen.getByTestId('threshold-marker')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('%');
  });

  it('threshold missing: text says so and there is no marker', () => {
    render(<AnomalyGauge status={s({ status: 'ok', score: 0.004, threshold: null })} />);
    expect(screen.getByTestId('anomaly-readout')).toHaveTextContent('threshold not reported');
    expect(screen.queryByTestId('threshold-marker')).toBeNull();
  });

  it('anomalous flashes; no other state does', () => {
    const a = render(<AnomalyGauge status={s({ status: 'anomalous', score: 0.02 })} />);
    expect(a.container.querySelector('.anomaly-flash-border')).not.toBeNull();
    a.unmount();
    const b = render(<AnomalyGauge status={s({ status: 'ok' })} />);
    expect(b.container.querySelector('.anomaly-flash-border')).toBeNull();
  });

  it('screen-reader text equals the visual state and there is no canvas', () => {
    const { container } = render(<AnomalyGauge status={s({ status: 'ok', score: 0.0123, threshold: 0.01, trained_on: 'synthetic' })} />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('aria-label')).toContain('No anomaly flagged');
    expect(img.getAttribute('aria-label')).toContain('score 0.0123 / threshold 0.0100');
    expect(img.getAttribute('aria-label')).toContain('Experimental — trained on simulator data');
    expect(container.querySelector('canvas')).toBeNull();
    expect(container.querySelector('[role="progressbar"], [role="meter"]')).toBeNull();
  });

  it('shows detector provenance: model version, trained-on and origin', () => {
    render(<AnomalyGauge status={s({ trained_on: 'synthetic', model_version: 'ae-1', origin: 'simulated' })} />);
    expect(screen.getByText('Experimental — trained on simulator data')).toBeInTheDocument();
    expect(screen.getByText('Model version: ae-1')).toBeInTheDocument();
    expect(screen.getByText('Origin: Simulated')).toBeInTheDocument();
  });
});

describe('AnomalyAlert', () => {
  it.each(FAIL_CLOSED)('renders no banner for %s', (_n, status) => {
    const { container } = render(<AnomalyAlert status={status} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders no banner for ok or warming_up', () => {
    expect(render(<AnomalyAlert status={s({ status: 'ok' })} />).container).toBeEmptyDOMElement();
    expect(render(<AnomalyAlert status={s({ status: 'warming_up', score: null })} />).container).toBeEmptyDOMElement();
  });

  it('renders an alert only for backend anomalous, with type, message and readout', () => {
    render(<AnomalyAlert status={s({ status: 'anomalous', score: 0.02, threshold: 0.01, type: 'thermal', message: 'Outlet rising' })} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Anomaly flagged');
    expect(alert).toHaveTextContent('thermal');
    expect(alert).toHaveTextContent('Outlet rising');
    expect(alert).toHaveTextContent('score 0.0200 / threshold 0.0100');
    expect(alert).not.toHaveTextContent('%');
  });

  it('the dismiss control has an accessible name, and a new episode shows the banner again', () => {
    const ep = (key: string) => s({ status: 'anomalous', score: 0.02, episode: { open: true, dedupe_key: key, alert_id: null, start_seq: 1, severity: null } });
    const { rerender } = render(<AnomalyAlert status={ep('a')} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss anomaly banner' }));
    expect(screen.queryByRole('alert')).toBeNull();
    rerender(<AnomalyAlert status={ep('a')} />);
    expect(screen.queryByRole('alert')).toBeNull();
    rerender(<AnomalyAlert status={ep('b')} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
