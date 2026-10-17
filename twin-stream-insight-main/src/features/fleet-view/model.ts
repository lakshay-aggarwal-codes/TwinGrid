/** Task 30: sorting, the lab link, and the site context. PURE except the tiny store at the bottom. */
import { useSyncExternalStore } from "react";
import type { Site } from "./schema";

export type SortKey = "overall" | "pue" | "carbon" | "alerts";

export const SORT_OPTIONS: ReadonlyArray<{ key: SortKey; label: string }> = [
  { key: "overall", label: "Overall" },
  { key: "pue", label: "PUE" },
  { key: "carbon", label: "Carbon" },
  { key: "alerts", label: "Alert conditions" },
];

const rankOf = (s: Site, key: SortKey): number =>
  key === "overall" ? s.overall_rank : key === "pue" ? s.rank.pue : key === "carbon" ? s.rank.carbon_gco2_per_step : s.rank.alert_conditions;

/** Best first for the chosen key; ties keep the backend's overall order, then id, so the list never jumps. */
export function sortSites(sites: readonly Site[], key: SortKey): Site[] {
  return [...sites].sort((a, b) => rankOf(a, key) - rankOf(b, key) || a.overall_rank - b.overall_rank || a.id.localeCompare(b.id));
}

export const rankFor = rankOf;

/** `/whatif-lab` URL that opens the lab with this site's load and ambient temperature (the lab holds water stress at 0). */
export function labLink(s: Site): string {
  const load = Math.round(s.inputs.utilisation * 100);
  return `/whatif-lab?load=${load}&amb=${encodeURIComponent(String(s.inputs.outside_temp_C))}&mode=auto`;
}

export function siteFromSearch(search: string, known: readonly string[]): string | null {
  const v = new URLSearchParams(search).get("site");
  return v !== null && known.includes(v) ? v : null;
}

export function withSite(search: string, id: string | null): string {
  const p = new URLSearchParams(search);
  if (id === null) p.delete("site");
  else p.set("site", id);
  const out = p.toString();
  return out ? `?${out}` : "";
}

// --- site context: the one place that says which simulated site the person is looking at -----------------------
let current: string | null = null;
const listeners = new Set<() => void>();

export const getSite = (): string | null => current;
export function setSite(id: string | null): void {
  if (id === current) return;
  current = id;
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void): (() => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export const useSite = (): string | null => useSyncExternalStore(subscribe, getSite, getSite);
