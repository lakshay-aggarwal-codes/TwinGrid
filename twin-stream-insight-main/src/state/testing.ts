/**
 * FE-03: Testing-Library helper so every later task can attach its a11y check.
 * Test-only: import from `*.test.tsx`, never from app code.
 */
import { STATE_VOCABULARY, type UiStateKind } from './dataState';

export interface ExpectStateOptions {
  /** Text (or pattern) the state must show. */
  text: string | RegExp;
  /** Scope the lookup (defaults to the whole document). */
  within?: HTMLElement;
}

/**
 * Asserts a state from the vocabulary is rendered with the right ARIA role (or none for inline states),
 * the expected text, and its non-colour icon cue. Returns the state element.
 */
export function expectState(kind: UiStateKind, options: ExpectStateOptions): HTMLElement {
  const root: ParentNode = options.within ?? document.body;
  const el = root.querySelector<HTMLElement>(`[data-state="${kind}"]`);
  if (!el) throw new Error(`State "${kind}" is not rendered`);

  const expectedRole = STATE_VOCABULARY[kind].role;
  const actualRole = el.getAttribute('role');
  if ((actualRole ?? null) !== expectedRole) {
    throw new Error(`State "${kind}": expected role ${expectedRole ?? 'none'}, got ${actualRole ?? 'none'}`);
  }

  const content = el.textContent ?? '';
  const matches = typeof options.text === 'string' ? content.includes(options.text) : options.text.test(content);
  if (!matches) throw new Error(`State "${kind}": ${String(options.text)} not found in "${content}"`);

  const icon = el.querySelector(`[data-state-icon="${kind}"]`);
  if (!icon || icon.getAttribute('aria-hidden') !== 'true') throw new Error(`State "${kind}": decorative icon cue missing`);
  return el;
}
