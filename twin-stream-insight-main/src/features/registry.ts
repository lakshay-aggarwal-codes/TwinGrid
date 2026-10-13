import { commandRegistry } from "./commands";
import { roleAllows } from "./roles";
import { SLOT_NAMES, type Command, type FeatureComponent, type FeatureModule, type FeatureRole, type SlotName, type SlotWidgetProps } from "./types";

/**
 * Paths owned by the core router in App.tsx. A feature may not claim one (or anything under one, except "/"
 * which is exact-only). features.registry.test.ts reads App.tsx and fails if this list drifts from it.
 */
export const CORE_ROUTE_PATHS: readonly string[] = ["/", "/analytics", "/runs", "/evaluation", "/telemetry", "/legacy"];

export interface FeatureRoute {
  featureId: string;
  path: string;
  component: FeatureComponent;
  minRole?: FeatureRole;
}
export interface NavEntry {
  featureId: string;
  path: string;
  label: string;
  icon: NonNullable<FeatureModule["nav"]>["icon"];
  group: string;
  order: number;
}
export interface NavGroup {
  group: string;
  items: NavEntry[];
}
export interface SlotWidget {
  key: string;
  featureId: string;
  component: FeatureComponent<SlotWidgetProps>;
  order: number;
}
export interface Rejection {
  id: string;
  reason: string;
}

export interface FeatureRegistry {
  features: readonly FeatureModule[];
  /** Modules that were refused (invalid shape, duplicate id, path clash). The rest of the app is unaffected. */
  rejected: readonly Rejection[];
  /** Every feature route, regardless of role (the route itself applies the role gate). */
  allRoutes(): FeatureRoute[];
  navGroups(role: string | null | undefined): NavGroup[];
  slotWidgets(slot: SlotName, role: string | null | undefined): SlotWidget[];
  allCommands(): Command[];
}

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;
const isRole = (v: unknown): v is FeatureRole | undefined => v === undefined || v === "viewer" || v === "operator" || v === "admin";
const isComponent = (v: unknown): boolean => typeof v === "function" || (typeof v === "object" && v !== null && "$$typeof" in v);
const normalise = (p: string) => (p.length > 1 && p.endsWith("/") ? p.slice(0, -1) : p);

function clashesWithCore(path: string, reserved: readonly string[]): boolean {
  return reserved.some((r) => (r === "/" ? path === "/" : path === r || path.startsWith(`${r}/`)));
}

/** Returns a reason when the module is unusable, else null. Pure; never throws on odd input. */
function validate(m: unknown, seenIds: Set<string>, seenPaths: Set<string>, reserved: readonly string[]): string | null {
  if (typeof m !== "object" || m === null) return "not an object";
  const f = m as Partial<FeatureModule>;
  if (typeof f.id !== "string" || !ID_RE.test(f.id)) return "id must be lowercase [a-z0-9-]";
  if (seenIds.has(f.id)) return "duplicate feature id";
  if (f.route) {
    const p = f.route.path;
    if (typeof p !== "string" || !p.startsWith("/") || /[*?#\s]/.test(p)) return "route.path must be absolute with no wildcard";
    if (clashesWithCore(normalise(p), reserved)) return "route.path collides with a core route";
    if (seenPaths.has(normalise(p))) return "route.path already used by another feature";
    if (!isComponent(f.route.component)) return "route.component missing";
    if (!isRole(f.route.minRole)) return "route.minRole invalid";
  }
  if (f.nav) {
    const n = f.nav;
    if (!f.route) return "nav requires route";
    if (typeof n.label !== "string" || n.label === "" || typeof n.group !== "string" || n.group === "") return "nav.label and nav.group required";
    if (!isComponent(n.icon) || !Number.isFinite(n.order) || !isRole(n.minRole)) return "nav.icon, nav.order or nav.minRole invalid";
  }
  if (f.commands !== undefined && !Array.isArray(f.commands)) return "commands must be an array";
  for (const s of f.slots ?? []) {
    if (!SLOT_NAMES.includes(s?.slot) || !isComponent(s.component) || !Number.isFinite(s.order) || !isRole(s.minRole)) return "invalid slot entry";
  }
  return null;
}

/** Builds a registry from already-imported modules. A bad module is rejected on its own; it never throws. */
export function createFeatureRegistry(
  modules: readonly unknown[],
  options: { reservedPaths?: readonly string[]; onReject?: (r: Rejection) => void } = {},
): FeatureRegistry {
  const reserved = options.reservedPaths ?? CORE_ROUTE_PATHS;
  const onReject = options.onReject ?? ((r: Rejection) => console.warn(`[features] rejected "${r.id}": ${r.reason}`));
  const accepted: FeatureModule[] = [];
  const rejected: Rejection[] = [];
  const ids = new Set<string>();
  const paths = new Set<string>();

  for (const m of modules) {
    const reason = validate(m, ids, paths, reserved);
    if (reason !== null) {
      const id = typeof (m as { id?: unknown } | null)?.id === "string" ? (m as { id: string }).id : "?";
      const r = { id, reason };
      rejected.push(r);
      onReject(r);
      continue;
    }
    const f = m as FeatureModule;
    ids.add(f.id);
    if (f.route) paths.add(normalise(f.route.path));
    accepted.push(f);
  }

  const routeMinRole = (f: FeatureModule) => f.route?.minRole ?? f.nav?.minRole;

  return {
    features: accepted,
    rejected,
    allRoutes: () =>
      accepted.filter((f) => f.route).map((f) => ({ featureId: f.id, path: normalise(f.route!.path), component: f.route!.component, minRole: routeMinRole(f) })),
    navGroups(role) {
      const entries: NavEntry[] = accepted
        .filter((f) => f.nav && f.route && roleAllows(role, f.nav.minRole))
        .map((f) => ({ featureId: f.id, path: normalise(f.route!.path), label: f.nav!.label, icon: f.nav!.icon, group: f.nav!.group, order: f.nav!.order }));
      entries.sort((a, b) => a.group.localeCompare(b.group) || a.order - b.order || a.label.localeCompare(b.label));
      const groups: NavGroup[] = [];
      for (const e of entries) {
        const last = groups[groups.length - 1];
        if (last && last.group === e.group) last.items.push(e);
        else groups.push({ group: e.group, items: [e] });
      }
      return groups;
    },
    slotWidgets(slot, role) {
      const out: SlotWidget[] = [];
      for (const f of accepted) {
        (f.slots ?? []).forEach((s, i) => {
          if (s.slot === slot && roleAllows(role, s.minRole)) out.push({ key: `${f.id}:${i}`, featureId: f.id, component: s.component, order: s.order });
        });
      }
      return out.sort((a, b) => a.order - b.order || a.featureId.localeCompare(b.featureId));
    },
    allCommands: () => accepted.flatMap((f) => [...(f.commands ?? [])]),
  };
}

/** Every `src/features/<name>/index.ts` default export, found at build time. */
export function discoverFeatureModules(): unknown[] {
  const found = import.meta.glob<{ default: unknown }>("./*/index.ts", { eager: true });
  return Object.keys(found)
    .sort()
    .map((k) => found[k].default);
}

/** The app-wide registry. Its commands are placed in the shared command registry once, here. */
export const featureRegistry: FeatureRegistry = createFeatureRegistry(discoverFeatureModules());
commandRegistry.register("features", featureRegistry.allCommands());
