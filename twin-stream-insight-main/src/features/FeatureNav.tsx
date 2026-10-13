import { useLocation } from "react-router-dom";
import { RotateLink } from "@/components/transition/RotateLink";
import { useRole } from "@/hooks/useAuth.ts";
import { featureRegistry, type FeatureRegistry } from "./registry";

interface FeatureNavProps {
  orientation: "vertical" | "horizontal";
  /** Icon-only (vertical sidebar collapsed). The accessible name is always the label. */
  collapsed?: boolean;
  /** Tests only. */
  registry?: FeatureRegistry;
}

/** Links to the pages features registered, grouped and role-filtered. Renders nothing when there are none. */
export function FeatureNav({ orientation, collapsed = false, registry = featureRegistry }: FeatureNavProps) {
  const { role } = useRole();
  const { pathname } = useLocation();
  const groups = registry.navGroups(role);
  if (groups.length === 0) return null;
  const vertical = orientation === "vertical";

  return (
    <nav aria-label="Feature pages" className={vertical ? "space-y-3" : "flex items-center gap-2"}>
      {groups.map((g) => (
        <div key={g.group} className={vertical ? "space-y-1" : "flex items-center gap-2"}>
          {vertical && !collapsed && (
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{g.group}</p>
          )}
          {g.items.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.path || pathname.startsWith(`${item.path}/`);
            return (
              <RotateLink
                key={item.featureId}
                to={item.path}
                aria-label={item.label}
                aria-current={active ? "page" : undefined}
                title={item.label}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  active ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"
                } ${collapsed ? "justify-center" : ""}`}
              >
                <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                {!collapsed && <span className={vertical ? "" : "hidden min-[1600px]:inline"}>{item.label}</span>}
              </RotateLink>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
