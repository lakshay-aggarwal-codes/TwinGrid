import type { ComponentType, LazyExoticComponent } from "react";
import type { LucideIcon } from "lucide-react";

/** Roles a feature may require, lowest to highest. The backend only issues viewer/operator today; "admin" is
 * reserved for the admin console (a feature asking for it is hidden from everyone until the backend issues it). */
export type FeatureRole = "viewer" | "operator" | "admin";

/** The four places a feature can put a widget without touching the host component's code. */
export const SLOT_NAMES = ["dashboard", "facility-inspector", "header-actions", "settings"] as const;
export type SlotName = (typeof SLOT_NAMES)[number];

/** A component, or a `React.lazy(...)` one (the route page of a feature should be lazy). */
export type FeatureComponent<P = object> = ComponentType<P> | LazyExoticComponent<ComponentType<P>>;

/** Props every slot widget receives. `context` is whatever the host passes (e.g. `{ rackId }` in facility-inspector). */
export interface SlotWidgetProps {
  context: Readonly<Record<string, unknown>>;
}

/** An action a feature contributes to the shared command registry (the Ctrl+K palette is built on it by Task 12). */
export interface Command {
  /** Unique across all features. */
  id: string;
  label: string;
  /** Palette group heading, e.g. "Navigate". */
  group?: string;
  /** Extra search terms. */
  keywords?: readonly string[];
  /** Display-only hint such as "G then R"; registering it does not bind the key. */
  shortcut?: string;
  minRole?: FeatureRole;
  run: () => void;
}

export interface FeatureModule {
  /** Unique, lowercase, `[a-z0-9-]`. */
  id: string;
  route?: {
    /** Absolute, e.g. "/replay". Must not collide with a core route (see CORE_ROUTE_PATHS). */
    path: string;
    component: FeatureComponent;
    /** Defaults to `nav.minRole`. UX gate only: the backend enforces roles on every request. */
    minRole?: FeatureRole;
  };
  /** A navigation entry; requires `route` (it links to it). */
  nav?: {
    label: string;
    icon: LucideIcon;
    group: string;
    order: number;
    minRole?: FeatureRole;
  };
  commands?: readonly Command[];
  slots?: readonly {
    slot: SlotName;
    component: FeatureComponent<SlotWidgetProps>;
    order: number;
    minRole?: FeatureRole;
  }[];
}
