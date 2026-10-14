import type { Command } from "../types";

/** One row in the palette. `id` is unique across sources (prefixed by the source). */
export interface PaletteItem {
  id: string;
  label: string;
  group: string;
  keywords: readonly string[];
  /** Display-only hint (e.g. "G then R"). */
  shortcut?: string;
  run: () => void;
}

/** Group order in the list; any other group (a feature's own heading) follows, alphabetically. */
export const GROUP_ORDER = ["Navigate", "Scenarios", "Racks", "Zones", "Alerts", "Actions"] as const;

export const CORE_PAGES: readonly { path: string; label: string; keywords: readonly string[] }[] = [
  { path: "/", label: "Live twin", keywords: ["3d", "facility", "home", "scene"] },
  { path: "/analytics", label: "Analytics", keywords: ["kpi", "simulation", "what-if", "sustainability", "charts"] },
  { path: "/runs", label: "New simulation run", keywords: ["runs", "run", "submit", "job"] },
  { path: "/evaluation", label: "Evaluation reports", keywords: ["policy", "evaluation", "ppo", "baseline"] },
  { path: "/telemetry", label: "Telemetry history", keywords: ["history", "samples", "sensors", "gaps"] },
];

export function pageItems(
  navigate: (path: string) => void,
  featurePages: readonly { path: string; label: string }[] = [],
): PaletteItem[] {
  const core = CORE_PAGES.map((p) => ({ ...p, id: `page:${p.path}` }));
  const extra = featurePages.map((p) => ({ path: p.path, label: p.label, keywords: [] as readonly string[], id: `page:${p.path}` }));
  const seen = new Set<string>();
  const out: PaletteItem[] = [];
  for (const p of [...core, ...extra]) {
    if (seen.has(p.id)) continue;
    seen.add(p.id);
    out.push({ id: p.id, label: `Go to ${p.label}`, group: "Navigate", keywords: [p.label, ...p.keywords], run: () => navigate(p.path) });
  }
  return out;
}

export interface ScenarioLike {
  id: string;
  label: string;
  description?: string | null;
}

/** One item per backend scenario. Choosing it selects it and opens the page that previews it; nothing is run. */
export function scenarioItems(
  scenarios: readonly ScenarioLike[],
  open: (scenarioId: string) => void,
): PaletteItem[] {
  return scenarios.map((s) => ({
    id: `scenario:${s.id}`,
    label: `Scenario: ${s.label}`,
    group: "Scenarios",
    keywords: [s.label, s.id, ...(s.description ? [s.description] : [])],
    run: () => open(s.id),
  }));
}

/** Registry commands (contributed by features) as palette rows. Ids stay unique by the `cmd:` prefix. */
export function commandItems(commands: readonly Command[]): PaletteItem[] {
  return commands.map((c) => ({
    id: `cmd:${c.id}`,
    label: c.label,
    group: c.group && c.group.trim() !== "" ? c.group : "Actions",
    keywords: [c.label, ...(c.keywords ?? [])],
    shortcut: c.shortcut,
    run: c.run,
  }));
}

/** First occurrence of an id wins. */
export function dedupe(items: readonly PaletteItem[]): PaletteItem[] {
  const seen = new Set<string>();
  return items.filter((i) => (seen.has(i.id) ? false : (seen.add(i.id), true)));
}

export interface ItemGroup {
  group: string;
  items: PaletteItem[];
}

export function groupItems(items: readonly PaletteItem[]): ItemGroup[] {
  const byGroup = new Map<string, PaletteItem[]>();
  for (const i of items) byGroup.set(i.group, [...(byGroup.get(i.group) ?? []), i]);
  const rank = (g: string) => {
    const idx = (GROUP_ORDER as readonly string[]).indexOf(g);
    return idx === -1 ? GROUP_ORDER.length : idx;
  };
  return [...byGroup.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([group, list]) => ({ group, items: list }));
}

/** Recent items in recency order; ids that no longer exist (feature removed, role changed) are dropped. */
export function resolveRecents(recentIds: readonly string[], items: readonly PaletteItem[]): PaletteItem[] {
  const byId = new Map(items.map((i) => [i.id, i]));
  return recentIds.flatMap((id) => {
    const found = byId.get(id);
    return found ? [found] : [];
  });
}
