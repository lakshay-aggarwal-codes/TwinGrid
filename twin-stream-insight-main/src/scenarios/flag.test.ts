import { describe, expect, it } from 'vitest';
import { isScenarioLibraryEnabled } from './flag';

describe('rollback flag', () => {
  it.each([[{}, true], [{ VITE_SCENARIO_LIBRARY: '' }, true], [{ VITE_SCENARIO_LIBRARY: 'on' }, true], [{ VITE_SCENARIO_LIBRARY: 'off' }, false], [{ VITE_SCENARIO_LIBRARY: ' OFF ' }, false]])('%j -> %s', (env, expected) => {
    expect(isScenarioLibraryEnabled(env)).toBe(expected);
  });
});
