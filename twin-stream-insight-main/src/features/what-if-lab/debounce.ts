/** Task 15: a trailing debouncer with injectable timers (so the behaviour is testable without real time). PURE. */
export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}
export const realTimers: Timers = { set: (fn, ms) => setTimeout(fn, ms), clear: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) };

export interface Debouncer<T> {
  /** Schedule `fire(value)` after `ms` of quiet; a newer push replaces the pending one. */
  push(value: T): void;
  /** Drop the pending call (unmount). */
  cancel(): void;
  /** Fire the pending call now, if any (Enter / blur). */
  flush(): void;
  readonly pending: boolean;
}

export function createDebouncer<T>(ms: number, fire: (value: T) => void, timers: Timers = realTimers): Debouncer<T> {
  let handle: unknown = null;
  let latest: { value: T } | null = null;
  const run = () => {
    handle = null;
    const l = latest;
    latest = null;
    if (l) fire(l.value);
  };
  return {
    push(value) {
      latest = { value };
      if (handle !== null) timers.clear(handle);
      if (ms <= 0) return run();
      handle = timers.set(run, ms);
    },
    cancel() {
      if (handle !== null) timers.clear(handle);
      handle = null;
      latest = null;
    },
    flush() {
      if (handle !== null) timers.clear(handle);
      run();
    },
    get pending() {
      return latest !== null;
    },
  };
}
