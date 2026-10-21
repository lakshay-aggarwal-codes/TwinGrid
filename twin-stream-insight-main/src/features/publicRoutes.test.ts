import { describe, expect, it } from 'vitest';
import appSource from '../App.tsx?raw';
import { CORE_ROUTE_PATHS } from './registry';

describe('AUTH-C public routes', () => {
  it('/access/pending and /activate are declared OUTSIDE the sign-in gate', () => {
    const gate = appSource.indexOf('<AuthGate>');
    expect(gate).toBeGreaterThan(0);
    for (const path of ['/access/pending', '/activate']) {
      const at = appSource.indexOf(`<Route path="${path}"`);
      expect(at, path).toBeGreaterThan(-1);
      expect(at, path).toBeLessThan(gate);
    }
  });
  it('both are reserved so a feature cannot shadow them', () => {
    expect(CORE_ROUTE_PATHS).toEqual(expect.arrayContaining(['/access', '/activate']));
  });
});
