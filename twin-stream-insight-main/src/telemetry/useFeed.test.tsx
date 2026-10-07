import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Profiler, useRef } from 'react';
import { render, screen, act } from '@testing-library/react';
import { createFeedStore, type FeedStore } from './feedStore';
import { FeedStoreContext, shallowEqual, useFeed } from './useFeed';
import { fakeClock, fakeTransport, liveFrame } from './testUtils';
import type { LiveStatePayload } from '@/api/apiClient';

let t: ReturnType<typeof fakeTransport>;
let store: FeedStore;
const send = (f: Partial<LiveStatePayload>) => act(() => t.h.onMessage!(liveFrame(f)));

function Counter({ id, sel }: { id: string; sel: Parameters<typeof useFeed>[0] }) {
  const renders = useRef(0);
  renders.current += 1;
  const v = useFeed(sel);
  return (
    <div data-testid={id} data-renders={renders.current}>
      {String(v)}
    </div>
  );
}
const renders = (id: string) => Number(screen.getByTestId(id).getAttribute('data-renders'));

beforeEach(() => {
  t = fakeTransport();
  store = createFeedStore({ connect: t.connect, clock: fakeClock() });
  store.start();
  act(() => t.h.onStatus!('open'));
});
afterEach(() => store.stop());

const ui = (
  <FeedStoreContext.Provider value={store}>
    <Counter id="mode" sel={(v) => v.frame?.value.cooling_mode} />
    <Counter id="pue" sel={(v) => v.frame?.value.pue} />
    <Counter id="state" sel={(v) => v.freshness.state} />
  </FeedStoreContext.Provider>
);

describe('useFeed selector isolation', () => {
  it('a tick that changes pue does not re-render a cooling_mode subscriber', () => {
    render(ui);
    send({ seq: 1, pue: 1.2, cooling_mode: 'hybrid' });
    const before = { mode: renders('mode'), pue: renders('pue'), state: renders('state') };

    send({ seq: 2, pue: 1.5, cooling_mode: 'hybrid' });
    expect(screen.getByTestId('pue')).toHaveTextContent('1.5');
    expect(renders('pue')).toBe(before.pue + 1);
    expect(renders('mode')).toBe(before.mode); // unchanged selected value -> no render
    expect(renders('state')).toBe(before.state);

    send({ seq: 3, pue: 1.5, cooling_mode: 'free_air' });
    expect(renders('mode')).toBe(before.mode + 1);
    expect(renders('pue')).toBe(before.pue + 1);
  });

  it('commits per tick: only subscribers whose selected value changed re-render (baseline for FE-20)', () => {
    let commits = 0;
    render(
      <Profiler id="feed" onRender={() => void (commits += 1)}>
        {ui}
      </Profiler>,
    );
    send({ seq: 1, pue: 1.2 });
    const start = commits;
    for (let i = 2; i <= 11; i++) send({ seq: i, pue: 1.2, cooling_mode: 'hybrid' }); // 10 ticks, nothing selected changes
    // The stamped frame object changes per tick, but none of these selectors return it: zero commits.
    expect(commits - start).toBe(0);
  });

  it('shallowEqual selectors avoid re-rendering on a new object with equal fields', () => {
    function Pair() {
      const renders = useRef(0);
      renders.current += 1;
      const p = useFeed((v) => ({ mode: v.frame?.value.cooling_mode, state: v.freshness.state }), shallowEqual);
      return <div data-testid="pair" data-renders={renders.current}>{p.mode}:{p.state}</div>;
    }
    render(<FeedStoreContext.Provider value={store}><Pair /></FeedStoreContext.Provider>);
    send({ seq: 1 });
    const r = renders('pair');
    send({ seq: 2, pue: 2 });
    expect(renders('pair')).toBe(r);
  });

  it('re-renders a freshness subscriber on a state transition', () => {
    render(ui);
    send({ seq: 1 });
    expect(screen.getByTestId('state')).toHaveTextContent('live');
    act(() => t.h.onStatus!('closed'));
    expect(screen.getByTestId('state')).toHaveTextContent('disconnected');
  });
});

describe('subscription lifecycle', () => {
  it('unmount unsubscribes every listener it added', () => {
    let active = 0;
    const original = store.subscribe;
    store.subscribe = (listener) => {
      active += 1;
      const off = original(listener);
      return () => {
        active -= 1;
        off();
      };
    };
    const { unmount } = render(ui);
    expect(active).toBe(3);
    unmount();
    expect(active).toBe(0);
  });

  it('throws a clear error outside the provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Counter id="x" sel={(v) => v.freshness.state} />)).toThrow(/SimulationProvider/);
    spy.mockRestore();
  });
});
