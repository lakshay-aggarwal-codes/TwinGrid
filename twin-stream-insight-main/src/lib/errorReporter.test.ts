import { beforeEach, describe, expect, it, vi } from 'vitest';
import { reportError, resetReporterState, shouldSend } from './errorReporter.ts';

describe('shouldSend throttling', () => {
  beforeEach(() => resetReporterState());

  it('sends the first occurrence, suppresses duplicates inside the window, allows again after it', () => {
    expect(shouldSend('a|boom', 1_000_000)).toBe(true);
    expect(shouldSend('a|boom', 1_010_000)).toBe(false);
    expect(shouldSend('a|boom', 1_031_000)).toBe(true);
  });

  it('treats different sources/messages independently', () => {
    expect(shouldSend('a|x', 2_000_000)).toBe(true);
    expect(shouldSend('b|x', 2_000_001)).toBe(true);
    expect(shouldSend('a|y', 2_000_002)).toBe(true);
  });

  it('caps reports per minute so a loop cannot flood the sink', () => {
    const t = 3_000_000;
    const results = Array.from({ length: 30 }, (_, i) => shouldSend(`k|${i}`, t + i));
    expect(results.filter(Boolean)).toHaveLength(20);
    expect(shouldSend('k|late', t + 60_001)).toBe(true);
  });
});

describe('reportError', () => {
  beforeEach(() => resetReporterState());

  it('logs once per throttle window and never throws on odd inputs', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    reportError('test', new Error('first'));
    reportError('test', new Error('first'));
    reportError('test', { weird: 'object' });
    reportError('test', undefined);
    expect(() => reportError('test', Symbol('x'))).not.toThrow();
    expect(spy).toHaveBeenCalledTimes(4);
    spy.mockRestore();
  });

  it('uses console.warn for warning level', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    reportError('test-ws', 'socket closed', 'warning');
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
