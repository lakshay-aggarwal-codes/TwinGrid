import { describe, expect, it } from 'vitest';
import { classifyOrigin } from '@/provenance';
import { originForProvenance } from './origin';

describe('origin alias (G-HIST difference #4)', () => {
  it('maps exactly `replay` to `replayed`', () => expect(originForProvenance('replay')).toBe('replayed'));
  it('replay shows as Replayed, not Unverified', () => expect(classifyOrigin(originForProvenance('replay')).state).toBe('replayed'));
  it.each(['simulated', 'measured', 'replayed'])('passes %s through', (o) => expect(originForProvenance(o)).toBe(o));
  it.each(['Replay', 'REPLAY', ' replay', 'replay ', 'imported', ''])('does not widen the alias: %j stays unknown', (o) => {
    expect(classifyOrigin(originForProvenance(o)).state).toBe('unverified');
  });
  it('absent origin is unverified, never simulated', () => {
    expect(originForProvenance(null)).toBeNull();
    expect(originForProvenance(undefined)).toBeNull();
    expect(classifyOrigin(originForProvenance(null)).state).toBe('unverified');
  });
});
