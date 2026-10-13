import { useMemo, useSyncExternalStore } from "react";
import { useRole } from "@/hooks/useAuth.ts";
import { commandRegistry, type CommandRegistry } from "./commands";
import type { Command } from "./types";

/** The commands the signed-in role may use; re-renders when a feature registers or removes commands. */
export function useCommands(registry: CommandRegistry = commandRegistry): Command[] {
  const version = useSyncExternalStore(registry.subscribe, registry.getVersion, registry.getVersion);
  const { role } = useRole();
  // `version` is the cache key: the registry's list is rebuilt only when it changed.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => registry.list(role), [registry, role, version]);
}
