import { describe, expect, it } from 'vitest';
import { isEvaluationViewEnabled } from './flag';

describe('isEvaluationViewEnabled', () => {
  it.each([[undefined, true], ['', true], ['on', true], ['off', false], [' OFF ', false]])('%j -> %j', (v, expected) => {
    expect(isEvaluationViewEnabled({ VITE_EVALUATION_VIEW: v })).toBe(expected);
  });
});
