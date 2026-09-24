import { describe, expect, it } from 'vitest';
import { deriveWsUrl, normalizeBaseUrl } from './config';

describe('normalizeBaseUrl', () => {
  it('strips trailing slashes and whitespace', () => {
    expect(normalizeBaseUrl('https://api.example.com/')).toBe('https://api.example.com');
    expect(normalizeBaseUrl('  http://localhost:8000///  ')).toBe('http://localhost:8000');
  });
  it('treats unset values as empty', () => {
    expect(normalizeBaseUrl(undefined)).toBe('');
    expect(normalizeBaseUrl(null)).toBe('');
  });
});

describe('deriveWsUrl', () => {
  it('maps https to wss and http to ws', () => {
    expect(deriveWsUrl('https://api.example.com')).toBe('wss://api.example.com/ws/live');
    expect(deriveWsUrl('http://localhost:8000')).toBe('ws://localhost:8000/ws/live');
  });
});
