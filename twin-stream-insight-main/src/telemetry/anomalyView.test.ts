import { describe, expect, it } from 'vitest';
import type { AnomalyStatusPayload } from '@/api/apiClient';
import { formatDetectorNumber, gaugeGeometry, toAnomalyView } from './anomalyView';

const base = (over: Partial<AnomalyStatusPayload> = {}): AnomalyStatusPayload => ({
  status: 'ok',
  message: 'm',
  score: 0.0123,
  threshold: 0.01,
  type: null,
  ...over,
});

describe('toAnomalyView: every status', () => {
  const cases: Array<[string, Partial<AnomalyStatusPayload>, { kind: string; label: RegExp; flagged: boolean; hasNumber: boolean }]> = [
    ['warming_up with progress', { status: 'warming_up', score: null, threshold: null, window_filled: 4, window_size: 12 }, { kind: 'warming_up', label: /^Warming up \(4\/12\)$/, flagged: false, hasNumber: false }],
    ['ok', { status: 'ok', score: 0.004, threshold: 0.01 }, { kind: 'ok', label: /^No anomaly flagged$/, flagged: false, hasNumber: true }],
    ['anomalous', { status: 'anomalous', score: 0.02, threshold: 0.01, type: 'thermal', message: 'hot' }, { kind: 'anomalous', label: /^Anomaly flagged$/, flagged: true, hasNumber: true }],
    ['unavailable', { status: 'unavailable', score: null, threshold: null }, { kind: 'unavailable', label: /^Detector unavailable$/, flagged: false, hasNumber: false }],
    ['error', { status: 'error', score: null, threshold: null }, { kind: 'error', label: /^Detector error$/, flagged: false, hasNumber: false }],
    ['unknown status', { status: 'recalibrating', score: 0.5, threshold: 0.1 }, { kind: 'unrecognised', label: /^Unrecognised detector status$/, flagged: false, hasNumber: false }],
  ];
  it.each(cases)('%s', (_name, over, want) => {
    const v = toAnomalyView(base(over));
    expect(v.kind).toBe(want.kind);
    expect(v.label).toMatch(want.label);
    expect(v.flagged).toBe(want.flagged);
    expect(v.readout !== undefined).toBe(want.hasNumber);
    expect(v.score !== undefined).toBe(want.hasNumber);
    expect(v.label + (v.readout ?? '')).not.toContain('%');
    expect(v.srText).toContain(v.label);
  });

  it('no status at all is "not reported", never normal', () => {
    for (const none of [null, undefined]) {
      const v = toAnomalyView(none);
      expect(v.kind).toBe('not_reported');
      expect(v.label).toBe('Detector status not reported');
      expect(v.flagged).toBe(false);
      expect(v.readout).toBeUndefined();
    }
  });

  it('every kind has a distinct icon id', () => {
    const icons = cases.map(([, o]) => toAnomalyView(base(o)).icon).concat(toAnomalyView(null).icon);
    expect(new Set(icons).size).toBe(icons.length);
  });

  it('only backend `anomalous` flags', () => {
    for (const status of ['warming_up', 'ok', 'unavailable', 'error', 'whatever']) expect(toAnomalyView(base({ status })).flagged).toBe(false);
    expect(toAnomalyView(base({ status: 'anomalous' })).flagged).toBe(true);
  });
});

describe('score and threshold text', () => {
  it('shows "score 0.0123 / threshold 0.0100" and never %', () => {
    const v = toAnomalyView(base({ score: 0.0123, threshold: 0.01 }));
    expect(v.readout).toBe('score 0.0123 / threshold 0.0100');
    expect(v.readout).not.toMatch(/%/);
  });

  it('threshold null while ok -> "threshold not reported", threshold never fabricated', () => {
    const v = toAnomalyView(base({ status: 'ok', score: 0.004, threshold: null }));
    expect(v.readout).toBe('score 0.0040 (threshold not reported)');
    expect(v.threshold).toBeUndefined();
    expect(gaugeGeometry(v)).toBeNull();
  });

  it('scored status with a missing score shows no number', () => {
    const v = toAnomalyView(base({ status: 'ok', score: null }));
    expect(v.readout).toBe('score not reported');
    expect(v.score).toBeUndefined();
  });

  it('a zero score is a real number and is shown as one', () => {
    expect(toAnomalyView(base({ score: 0, threshold: 0.01 })).readout).toBe('score 0.0000 / threshold 0.0100');
  });

  it('formats tiny and large values without rescaling', () => {
    expect(formatDetectorNumber(0.00001234)).toBe('1.23e-5');
    expect(formatDetectorNumber(12.5)).toBe('12.5000');
  });

  it('warming up without window numbers does not invent progress', () => {
    const v = toAnomalyView(base({ status: 'warming_up', score: null, threshold: null }));
    expect(v.label).toBe('Warming up (progress not reported)');
    expect(v.warmup).toBeUndefined();
  });

  it('non-scored states never expose the backend score even if one is present', () => {
    for (const status of ['warming_up', 'unavailable', 'error', 'weird']) {
      const v = toAnomalyView(base({ status, score: 0.9, threshold: 0.1 }));
      expect(v.score).toBeUndefined();
      expect(v.readout).toBeUndefined();
    }
  });
});

describe('detector provenance', () => {
  it('synthetic training data -> experimental, trained on simulator data', () => {
    const v = toAnomalyView(base({ trained_on: 'synthetic', model_version: 'ae-1', origin: 'simulated' }));
    expect(v.provenance).toEqual({
      originText: 'Origin: Simulated',
      modelVersionText: 'Model version: ae-1',
      trainedOnText: 'Experimental — trained on simulator data',
      experimental: true,
    });
  });

  it('missing fields read "not reported"; absent or unknown origin is an unverified source', () => {
    const v = toAnomalyView(base({ trained_on: undefined, model_version: null, origin: undefined }));
    expect(v.provenance.modelVersionText).toBe('Model version: not reported');
    expect(v.provenance.trainedOnText).toBe('Training data: not reported');
    expect(v.provenance.originText).toBe('Origin: Unverified source');
    expect(toAnomalyView(base({ origin: 'lab-bench' })).provenance.originText).toBe('Origin: Unverified source');
    expect(v.provenance.experimental).toBe(false);
  });

  it('a non-synthetic trained_on is passed through as the backend said it, without a quality claim', () => {
    const v = toAnomalyView(base({ trained_on: 'plant-2025' }));
    expect(v.provenance.trainedOnText).toBe('Trained on: plant-2025');
    expect(v.srText).not.toMatch(/accura|quality|reliab/i);
  });
});

describe('gaugeGeometry', () => {
  const view = (score: number, threshold: number | null) => toAnomalyView(base({ status: 'ok', score, threshold }));

  it('puts the threshold marker at the midpoint and fills proportionally to score / threshold', () => {
    expect(gaugeGeometry(view(0.005, 0.01))).toEqual({ fillFraction: 0.25, markerFraction: 0.5, overflow: false });
    expect(gaugeGeometry(view(0.01, 0.01))).toEqual({ fillFraction: 0.5, markerFraction: 0.5, overflow: false });
    expect(gaugeGeometry(view(0.015, 0.01))?.fillFraction).toBeCloseTo(0.75);
  });

  it('clamps and flags overflow beyond twice the threshold', () => {
    expect(gaugeGeometry(view(0.05, 0.01))).toEqual({ fillFraction: 1, markerFraction: 0.5, overflow: true });
  });

  it('returns null without a positive backend threshold or for non-scored states', () => {
    expect(gaugeGeometry(view(0.01, null))).toBeNull();
    expect(gaugeGeometry(view(0.01, 0))).toBeNull();
    expect(gaugeGeometry(toAnomalyView(base({ status: 'unavailable' })))).toBeNull();
    expect(gaugeGeometry(toAnomalyView(null))).toBeNull();
  });
});

describe('legacy fail-open numbers are gone', () => {
  const files = import.meta.glob(['../components/AnomalyGauge.tsx', '../components/AnomalyAlert.tsx', './anomalyView.ts'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;
  const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

  it('no 5 / 30 / 60 thresholds, no Math.round score, no NOMINAL label', () => {
    expect(Object.keys(files)).toHaveLength(3);
    for (const [path, src] of Object.entries(files)) {
      const code = strip(src);
      expect(code, path).not.toMatch(/score\s*[<>]=?\s*(5|30|60)\b/);
      expect(code, path).not.toMatch(/Math\.round\(\s*(score|anomalyScore)/);
      expect(code, path).not.toMatch(/NOMINAL|ELEVATED|CRITICAL/);
      expect(code, path).not.toMatch(/`\$\{[^}]*\}%`/);
    }
  });
});
