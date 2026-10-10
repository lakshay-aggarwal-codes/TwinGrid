import { describe, expect, it } from 'vitest';
import { loadSelectedId, resolveSelection, saveSelectedId, SELECTION_KEY } from './selection';

const memory = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m };
};

describe('selection by id', () => {
  it('survives a "reload" (a new reader of the same storage) as the opaque id', () => {
    const store = memory();
    saveSelectedId('whatif-heat-wave', store);
    expect(store.m.get(SELECTION_KEY)).toBe('whatif-heat-wave');
    expect(loadSelectedId(store)).toBe('whatif-heat-wave');
  });
  it('clears with null', () => {
    const store = memory();
    saveSelectedId('a', store);
    saveSelectedId(null, store);
    expect(loadSelectedId(store)).toBeNull();
  });
  it('is quiet when storage throws or is absent', () => {
    const broken = { getItem: () => { throw new Error('x'); }, setItem: () => { throw new Error('x'); }, removeItem: () => { throw new Error('x'); } };
    expect(loadSelectedId(broken)).toBeNull();
    expect(() => saveSelectedId('a', broken)).not.toThrow();
    expect(loadSelectedId(null)).toBeNull();
  });
  it('resolves against the listed ids; an id no longer listed is "missing", never swapped for another', () => {
    expect(resolveSelection(null, ['a'])).toEqual({ status: 'none' });
    expect(resolveSelection('a', ['a', 'b'])).toEqual({ status: 'selected', id: 'a' });
    expect(resolveSelection('gone', ['a', 'b'])).toEqual({ status: 'missing', id: 'gone' });
  });
});
