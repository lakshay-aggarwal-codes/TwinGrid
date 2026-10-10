import { describe, expect, it } from 'vitest';
import { isTelemetryHistoryEnabled } from './flag';

describe('isTelemetryHistoryEnabled', () => {
  it('is on by default and for any value except off', () => {
    expect(isTelemetryHistoryEnabled({})).toBe(true);
    expect(isTelemetryHistoryEnabled({ VITE_TELEMETRY_HISTORY: 'on' })).toBe(true);
  });
  it('off (any case, padded) turns it off', () => {
    expect(isTelemetryHistoryEnabled({ VITE_TELEMETRY_HISTORY: 'off' })).toBe(false);
    expect(isTelemetryHistoryEnabled({ VITE_TELEMETRY_HISTORY: ' OFF ' })).toBe(false);
  });
});
