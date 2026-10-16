import { Activity, Boxes, type LucideIcon } from "lucide-react";
import type { NavGroup } from "../registry";

export interface MobileNavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

/** The two core pages, then every page a feature registered for this role (already role-filtered by the registry). */
export function mobileNavItems(groups: readonly NavGroup[]): MobileNavItem[] {
  const core: MobileNavItem[] = [
    { path: "/", label: "Live Twin", icon: Boxes },
    { path: "/analytics", label: "Analytics", icon: Activity },
  ];
  const seen = new Set(core.map((c) => c.path));
  for (const g of groups) {
    for (const item of g.items) {
      if (seen.has(item.path)) continue;
      seen.add(item.path);
      core.push({ path: item.path, label: item.label, icon: item.icon });
    }
  }
  return core;
}

/** `/replay/x` is on `/replay`; `/` is only on `/`. */
export function isActivePath(pathname: string, path: string): boolean {
  return path === "/" ? pathname === "/" : pathname === path || pathname.startsWith(`${path}/`);
}
