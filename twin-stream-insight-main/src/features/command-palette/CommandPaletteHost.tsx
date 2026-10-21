import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useInRouterContext, useNavigate } from "react-router-dom";
import { QueryClientContext } from "@tanstack/react-query";
import { useRole } from "@/hooks/useAuth.ts";
import { reportError } from "@/lib/errorReporter";
import { isScenarioLibraryEnabled, saveSelectedId, useScenarios } from "@/scenarios";
import { commandRegistry, type CommandRegistry } from "../commands";
import { featureRegistry, type FeatureRegistry } from "../registry";
import { useCommands } from "../useCommands";
import { CommandPalette } from "./CommandPalette";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { commandItems, dedupe, pageItems, scenarioItems, type PaletteItem } from "./items";
import { loadRecents, pushRecent } from "./recents";
import { isHelpShortcut, isPaletteShortcut } from "./shortcuts";

/** Another modal (report viewer, the live twin's own search) is on screen: do not stack a second one on top. */
const otherDialogOpen = () => typeof document !== "undefined" && document.querySelector('[role="dialog"]') !== null;

const captureFocus = (): HTMLElement | null => {
  const active = typeof document === "undefined" ? null : document.activeElement;
  return active instanceof HTMLElement && active !== document.body ? active : null;
};

/** After a dismissal (not after running a command, which may have moved focus on purpose). */
const restoreFocus = (el: HTMLElement | null) => {
  window.setTimeout(() => {
    if (el && el.isConnected && document.activeElement !== el) el.focus();
  }, 0);
};

/** Loads the backend scenarios, only while the palette is open (this component is mounted by the dialog). */
function ScenarioSource({ onItems, openScenario }: { onItems: (items: PaletteItem[]) => void; openScenario: (id: string) => void }) {
  const { state } = useScenarios();
  const scenarios = state.status === "ready" ? state.data.scenarios : null;
  useEffect(() => {
    onItems(scenarios ? scenarioItems(
            scenarios.flatMap((s) => (typeof s.id === "string" && typeof s.label === "string" ? [{ id: s.id, label: s.label, description: s.description }] : [])),
            openScenario,
          ) : []);
    return () => onItems([]);
  }, [scenarios, onItems, openScenario]);
  return null;
}

interface HostProps {
  navigate?: (path: string) => void;
  /** Tests only. */
  registry?: CommandRegistry;
  features?: FeatureRegistry;
}

export function PaletteHost({ navigate, registry = commandRegistry, features = featureRegistry }: HostProps) {
  const { role } = useRole();
  const commands = useCommands(registry);
  const hasQueryClient = useContext(QueryClientContext) !== undefined;
  const [open, setOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [recentIds, setRecentIds] = useState<string[]>(() => loadRecents());
  const [scenarioRows, setScenarioRows] = useState<PaletteItem[]>([]);
  const openRef = useRef(false);
  const helpRef = useRef(false);
  const returnFocus = useRef<HTMLElement | null>(null);

  const openPalette = useCallback(() => {
    returnFocus.current = captureFocus();
    setRecentIds(loadRecents());
    openRef.current = true;
    setOpen(true);
  }, []);
  const closePalette = useCallback((restore: boolean) => {
    openRef.current = false;
    setOpen(false);
    if (restore) restoreFocus(returnFocus.current);
  }, []);
  const openHelp = useCallback(() => {
    returnFocus.current = captureFocus();
    helpRef.current = true;
    setHelpOpen(true);
  }, []);
  const closeHelp = useCallback(() => {
    helpRef.current = false;
    setHelpOpen(false);
    restoreFocus(returnFocus.current);
  }, []);

  // Capture phase, so Ctrl/Cmd+K is ours on every page (the live twin's own handler never sees it) and `?` works
  // wherever focus is, except inside a text field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (isPaletteShortcut(e)) {
        if (openRef.current) {
          e.preventDefault();
          e.stopPropagation();
          closePalette(true);
        } else if (!helpRef.current && !otherDialogOpen()) {
          e.preventDefault();
          e.stopPropagation();
          openPalette();
        }
        return;
      }
      if (isHelpShortcut(e) && !openRef.current && !helpRef.current && !otherDialogOpen()) {
        e.preventDefault();
        openHelp();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [openPalette, closePalette, openHelp]);

  const openScenario = useCallback(
    (id: string) => {
      saveSelectedId(id);
      navigate?.("/analytics");
    },
    [navigate],
  );

  const items = useMemo(() => {
    const pages = navigate
      ? pageItems(navigate, features.navGroups(role).flatMap((g) => g.items.map((i) => ({ path: i.path, label: i.label }))))
      : [];
    return dedupe([...pages, ...scenarioRows, ...commandItems(commands)]);
  }, [navigate, features, role, scenarioRows, commands]);

  const shortcutHints = useMemo(
    () => commands.filter((c) => c.shortcut).map((c) => ({ keys: c.shortcut as string, description: c.label })),
    [commands],
  );

  const run = (item: PaletteItem) => {
    closePalette(false);
    setRecentIds(pushRecent(item.id));
    try {
      item.run();
    } catch (e) {
      reportError("command-palette.run", e);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={openPalette}
        aria-haspopup="dialog"
        aria-keyshortcuts="Control+K Meta+K"
        title="Command palette (Ctrl K)"
        className="underline underline-offset-2 hover:text-foreground"
      >
        Commands <kbd className="rounded border border-border px-1 font-mono text-[10px]">Ctrl K</kbd>
      </button>
      <CommandPalette
        open={open}
        onOpenChange={(next) => (next ? openPalette() : closePalette(true))}
        items={items}
        recentIds={recentIds}
        onRun={run}
        sources={
          navigate && hasQueryClient && isScenarioLibraryEnabled() ? (
            <ScenarioSource onItems={setScenarioRows} openScenario={openScenario} />
          ) : null
        }
      />
      <ShortcutsDialog open={helpOpen} onOpenChange={(next) => (next ? openHelp() : closeHelp())} extra={shortcutHints} />
    </>
  );
}

function RouterHost() {
  const navigate = useNavigate();
  return <PaletteHost navigate={(path) => navigate(path)} />;
}

/** The `settings`-slot widget (the account bar is on every page once signed in). Works with or without a router. */
export default function CommandPaletteWidget() {
  return useInRouterContext() ? <RouterHost /> : <PaletteHost />;
}
