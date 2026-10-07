import { beforeEach, describe, expect, it, vi } from 'vitest';
import { redactSecrets, reportError, resetReporterState } from './errorReporter.ts';

describe('redactSecrets', () => {
  it('redacts the WebSocket token in a URL query', () => {
    expect(redactSecrets('wss://h/ws/live?token=eyJhbGciOi.abc.def')).toBe('wss://h/ws/live?token=[redacted]');
    expect(redactSecrets('wss://h/ws/live?a=1&token=abc&b=2')).toBe('wss://h/ws/live?a=1&token=[redacted]&b=2');
  });

  it('redacts a quoted URL inside a SyntaxError-style message', () => {
    const msg = "Failed to construct 'WebSocket': The URL 'wss://h/ws/live?token=SECRET' is invalid.";
    expect(redactSecrets(msg)).not.toContain('SECRET');
  });

  it('redacts bearer tokens', () => {
    expect(redactSecrets('Authorization: Bearer abc.def-ghi_jkl')).toBe('Authorization: Bearer [redacted]');
  });

  it('leaves ordinary text alone', () => {
    expect(redactSecrets('WebSocket closed (code 1006); reconnecting')).toBe('WebSocket closed (code 1006); reconnecting');
  });
});

describe('reportError redaction', () => {
  beforeEach(() => resetReporterState());

  it('never writes a token to the console, from the message or the stack', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const err = new Error('bad url wss://h/ws/live?token=SECRET123');
    err.stack = 'Error: x\n at wss://h/ws/live?token=SECRET123';
    reportError('redaction.test', err);
    expect(JSON.stringify(spy.mock.calls)).not.toContain('SECRET123');
    spy.mockRestore();
  });
});
