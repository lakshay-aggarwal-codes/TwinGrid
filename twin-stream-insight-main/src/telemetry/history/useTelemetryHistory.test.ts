import { describe, expect, it, vi } from 'vitest';
import { MAX_PAGES, PAGE_LIMIT, loadHistory } from './useTelemetryHistory';
import { CAPTURED_GAPS, CAPTURED_PAGE_1, CAPTURED_PAGE_2, SENSOR_ID, SYNTHETIC_PAGE, clone } from './testFixtures';

const window = { from: '2026-03-01T00:00:00Z', to: '2026-03-02T00:00:00Z' };
const gaps = vi.fn(async () => clone(CAPTURED_GAPS));

describe('loadHistory', () => {
  it('follows next_cursor to the last page and reports nothing more available', async () => {
    const samples = vi.fn(async (_id: string, p: { cursor?: string | null }) => p.cursor ? { ...clone(CAPTURED_PAGE_2), next_cursor: null } : clone(CAPTURED_PAGE_1));
    const d = await loadHistory(SENSOR_ID, window, undefined, { samples, gaps } as never);
    expect(samples).toHaveBeenCalledTimes(2);
    expect(samples.mock.calls[1][1].cursor).toBe(CAPTURED_PAGE_1.next_cursor);
    expect(d.items).toHaveLength(CAPTURED_PAGE_1.items.length + CAPTURED_PAGE_2.items.length);
    expect(d.moreAvailable).toBe(false);
    expect(d.unit).toBe('kW');
    expect(d.gaps).toHaveLength(1);
  });

  it('every request is capped: page size is the backend maximum and the page count is capped', async () => {
    const samples = vi.fn(async (_id: string, p: { limit: number; cursor?: string | null }) => {
      const idx = Number(p.cursor ?? 0);
      return SYNTHETIC_PAGE(PAGE_LIMIT, idx * PAGE_LIMIT, String(idx + 1));
    });
    const d = await loadHistory(SENSOR_ID, window, undefined, { samples, gaps } as never);
    expect(samples).toHaveBeenCalledTimes(MAX_PAGES);
    expect(samples.mock.calls.every((c) => c[1].limit === PAGE_LIMIT)).toBe(true);
    expect(d.pagesLoaded).toBe(MAX_PAGES);
    expect(d.items).toHaveLength(MAX_PAGES * PAGE_LIMIT);
    expect(d.moreAvailable).toBe(true); // stated on screen; nothing is downsampled
  });

  it('a series that ends exactly at the cap is not reported as truncated', async () => {
    const samples = vi.fn(async (_id: string, p: { cursor?: string | null }) => {
      const idx = Number(p.cursor ?? 0);
      return SYNTHETIC_PAGE(10, idx * 10, idx + 1 < MAX_PAGES ? String(idx + 1) : null);
    });
    const d = await loadHistory(SENSOR_ID, window, undefined, { samples, gaps } as never);
    expect(d.moreAvailable).toBe(false);
  });

  it('a failing later page fails the whole load (no silent partial history)', async () => {
    const samples = vi.fn(async (_id: string, p: { cursor?: string | null }) => {
      if (p.cursor) throw new Error('boom');
      return clone(CAPTURED_PAGE_1);
    });
    await expect(loadHistory(SENSOR_ID, window, undefined, { samples, gaps } as never)).rejects.toThrow('boom');
  });
});
