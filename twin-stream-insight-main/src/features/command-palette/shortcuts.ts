/** Pure keyboard rules for the command palette. No DOM state is read except the event's own target. */

export interface ShortcutInfo {
  readonly keys: string;
  readonly description: string;
}

/** Shown in the `?` dialog. Registry commands that carry a `shortcut` hint are listed there too. */
export const BUILT_IN_SHORTCUTS: readonly ShortcutInfo[] = [
  { keys: "Ctrl K / ⌘ K", description: "Open or close the command palette" },
  { keys: "?", description: "Show this list of shortcuts" },
  { keys: "↑ ↓", description: "Move through palette results" },
  { keys: "Enter", description: "Run the highlighted command" },
  { keys: "Esc", description: "Close the palette or this list; focus returns to where you were" },
];

/** True for elements where a typed character is text, so a bare-key shortcut such as `?` must not fire. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (typeof HTMLElement === "undefined" || !(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  const role = target.getAttribute("role");
  return role === "textbox" || role === "combobox" || role === "searchbox";
}

type KeyLike = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey"> & { target?: EventTarget | null };

/** Ctrl+K (Windows/Linux) or Cmd+K (macOS), with no other modifier. */
export function isPaletteShortcut(e: KeyLike): boolean {
  return (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k";
}

/** `?` typed outside a text field. Shift is expected (it is how `?` is typed), Ctrl/Cmd/Alt are not. */
export function isHelpShortcut(e: KeyLike): boolean {
  return e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey && !isEditableTarget(e.target ?? null);
}
