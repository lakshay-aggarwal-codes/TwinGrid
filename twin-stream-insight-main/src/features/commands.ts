import type { Command } from "./types";
import { roleAllows } from "./roles";

/**
 * The shared command registry. Features contribute commands through their module (`FeatureModule.commands`);
 * the command palette (Task 12) and anything else that wants actions reads from here. Ids are unique: a
 * duplicate registration is rejected (first one wins) rather than silently replacing an action.
 */
export interface CommandRegistry {
  /** Adds commands under `source`; returns a function that removes exactly those commands. */
  register(source: string, commands: readonly Command[]): () => void;
  /** Commands the role may see, in registration order. */
  list(role: string | null | undefined): Command[];
  get(id: string): Command | undefined;
  subscribe(listener: () => void): () => void;
  /** Changes whenever the set of commands changes (the snapshot for `useSyncExternalStore`). */
  getVersion(): number;
}

export function createCommandRegistry(onReject: (id: string, reason: string) => void = warnReject): CommandRegistry {
  const byId = new Map<string, { command: Command; source: string }>();
  const listeners = new Set<() => void>();
  let version = 0;
  const bump = () => {
    version += 1;
    for (const l of [...listeners]) l();
  };

  return {
    register(source, commands) {
      const added: string[] = [];
      for (const command of commands) {
        if (typeof command?.id !== "string" || command.id === "" || typeof command.label !== "string" || typeof command.run !== "function") {
          onReject(String((command as { id?: unknown })?.id ?? "?"), "invalid command");
          continue;
        }
        if (byId.has(command.id)) {
          onReject(command.id, `duplicate command id (already registered by ${byId.get(command.id)!.source})`);
          continue;
        }
        byId.set(command.id, { command, source });
        added.push(command.id);
      }
      if (added.length > 0) bump();
      return () => {
        let removed = false;
        for (const id of added) {
          if (byId.get(id)?.source === source) {
            byId.delete(id);
            removed = true;
          }
        }
        if (removed) bump();
      };
    },
    list(role) {
      return [...byId.values()].map((e) => e.command).filter((c) => roleAllows(role, c.minRole));
    },
    get(id) {
      return byId.get(id)?.command;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getVersion: () => version,
  };
}

function warnReject(id: string, reason: string): void {
  console.warn(`[commands] rejected "${id}": ${reason}`);
}

/** The app-wide registry. */
export const commandRegistry = createCommandRegistry();
