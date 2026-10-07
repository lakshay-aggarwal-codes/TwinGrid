/** jsdom has no ResizeObserver; Radix slider/select need one. */
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= RO;
