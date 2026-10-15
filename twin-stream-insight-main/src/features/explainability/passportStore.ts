/**
 * Task 18: which Model Passport is open. One global drawer (mounted once, by the header widget) is opened from any
 * model-driven widget, a command or a deep link, so a widget needs no provider and no query just to offer the button.
 */
export interface PassportOpenState {
  readonly open: boolean;
  /** Restrict the drawer to one model kind (`anomaly`, `forecaster`, `ppo`), or null for every model. */
  readonly kind: string | null;
}

const CLOSED: PassportOpenState = { open: false, kind: null };
let state: PassportOpenState = CLOSED;
const listeners = new Set<() => void>();

const set = (next: PassportOpenState) => {
  state = next;
  listeners.forEach((l) => l());
};

export const openPassport = (kind: string | null = null): void => set({ open: true, kind });
export const closePassport = (): void => set({ open: false, kind: state.kind });
export const getPassportState = (): PassportOpenState => state;
export const subscribePassport = (l: () => void): (() => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};
/** Tests only. */
export const resetPassportStore = (): void => set(CLOSED);
