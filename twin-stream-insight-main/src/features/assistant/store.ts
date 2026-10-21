/** Task 15: which assistant context is open. One global drawer (mounted once, by the header widget) is opened from any entry point. */
import type { ContextRef } from "./schema";

export interface AssistantOpenState {
  readonly open: boolean;
  readonly context: ContextRef;
  /** Bumps on every open so the drawer starts a fresh conversation for a new context. */
  readonly nonce: number;
}

const GENERAL: ContextRef = { kind: "general" };
let state: AssistantOpenState = { open: false, context: GENERAL, nonce: 0 };
const listeners = new Set<() => void>();
const set = (next: AssistantOpenState) => {
  state = next;
  listeners.forEach((l) => l());
};

export const openAssistant = (context: ContextRef = GENERAL): void => set({ open: true, context, nonce: state.nonce + 1 });
export const closeAssistant = (): void => set({ ...state, open: false });
export const getAssistantState = (): AssistantOpenState => state;
export const subscribeAssistant = (l: () => void): (() => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};
/** Tests only. */
export const resetAssistantStore = (): void => set({ open: false, context: GENERAL, nonce: 0 });
