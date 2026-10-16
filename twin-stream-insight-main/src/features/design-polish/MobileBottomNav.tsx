import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useInRouterContext, useLocation } from "react-router-dom";
import { RotateLink } from "@/components/transition/RotateLink";
import { useAuth, useRole } from "@/hooks/useAuth.ts";
import { featureRegistry, type FeatureRegistry } from "../registry";
import type { SlotWidgetProps } from "../types";
import { isActivePath, mobileNavItems } from "./navItems";

/** Phones only (hidden from 640px up, where the header carries navigation). Signed-in pages only. Needs a Router. */
export function MobileBottomNav({ registry = featureRegistry }: { registry?: FeatureRegistry }) {
  // Without a Router there are no links to render (isolated component tests); render nothing rather than throw.
  return useInRouterContext() ? <BottomNav registry={registry} /> : null;
}

function BottomNav({ registry }: { registry: FeatureRegistry }) {
  const { status } = useAuth();
  const { role } = useRole();
  const { pathname } = useLocation();
  const signedIn = status === "signed-in";

  // Lets CSS reserve room at the bottom of the page (see index.css `.app-shell`) while the nav exists.
  useEffect(() => {
    if (!signedIn) return;
    document.documentElement.dataset.mobileNav = "1";
    return () => {
      delete document.documentElement.dataset.mobileNav;
    };
  }, [signedIn]);

  if (!signedIn) return null;
  const items = mobileNavItems(registry.navGroups(role));

  return createPortal(
    <nav
      aria-label="Main"
      data-testid="mobile-bottom-nav"
      className="fixed inset-x-0 bottom-0 z-40 flex h-11 items-stretch overflow-x-auto border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom,0px)] shadow-elevation-2 backdrop-blur-sm sm:hidden"
    >
      {items.map(({ path, label, icon: Icon }) => {
        const active = isActivePath(pathname, path);
        return (
          <RotateLink
            key={path}
            to={path}
            aria-current={active ? "page" : undefined}
            className={`flex min-w-[4.5rem] flex-1 flex-col items-center justify-center gap-0.5 px-2 text-caption transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
              active ? "border-t-2 border-primary text-primary" : "border-t-2 border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon aria-hidden="true" className="h-4 w-4" />
            <span className="whitespace-nowrap">{label}</span>
          </RotateLink>
        );
      })}
    </nav>,
    document.body,
  );
}

/** The `settings`-slot entry. */
export default function MobileBottomNavSlotWidget(_props: SlotWidgetProps) {
  return <MobileBottomNav />;
}
