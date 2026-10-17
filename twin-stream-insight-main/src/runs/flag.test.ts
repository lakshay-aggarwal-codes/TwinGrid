import { describe, expect, it } from 'vitest';
import { isRunWorkflowEnabled } from './flag';

describe('rollback flag', () => {
  it.each([[{}, true], [{ VITE_RUN_WORKFLOW: '' }, true], [{ VITE_RUN_WORKFLOW: 'on' }, true], [{ VITE_RUN_WORKFLOW: 'off' }, false], [{ VITE_RUN_WORKFLOW: ' OFF ' }, false]])('%j -> %s', (env, expected) => {
    expect(isRunWorkflowEnabled(env)).toBe(expected);
  });
});
