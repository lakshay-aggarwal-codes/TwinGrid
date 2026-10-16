import "@/test/resizeObserver";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { Boxes } from "lucide-react";
import { createFeatureRegistry } from "../registry";
import type { FeatureModule } from "../types";

let status = "signed-in";
vi.mock("@/hooks/useAuth.ts", () => ({
  useAuth: () => ({ status }),
  useRole: () => ({ role: "viewer" }),
}));
vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ to, children, ...rest }: { to: string; children: ReactNode }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

import ThemeToggle from "./ThemeToggle";
import { MobileBottomNav } from "./MobileBottomNav";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import type { SimConfig } from "@/hooks/useSimulation";
import { THEME_STORAGE_KEY } from "./theme";

const quiet = { onReject: () => undefined };
const feature: FeatureModule = {
  id: "demo",
  route: { path: "/replay", component: () => null },
  nav: { label: "Replay", icon: Boxes, group: "Operate", order: 1 },
};
const registry = createFeatureRegistry([feature], quiet);

beforeEach(() => {
  status = "signed-in";
  localStorage.clear();
});
afterEach(() => {
  delete document.documentElement.dataset.theme;
  document.documentElement.classList.remove("light");
});

describe("ThemeToggle", () => {
  it("is one named toggle button; pressing it switches the theme, saves it, and pressing again restores dark", () => {
    render(<ThemeToggle context={{}} />);
    const btn = screen.getByRole("button", { name: "Light theme" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("starts pressed when light was saved", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle context={{}} />);
    expect(screen.getByRole("button", { name: "Light theme" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("MobileBottomNav", () => {
  const renderNav = (path = "/analytics") =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <MobileBottomNav registry={registry} />
      </MemoryRouter>,
    );

  it("is a landmark named Main with a link per core page and per feature page; the current page is marked", () => {
    renderNav("/analytics");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Live Twin" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Replay" })).toHaveAttribute("href", "/replay");
    expect(screen.getByRole("link", { name: "Analytics" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Live Twin" })).not.toHaveAttribute("aria-current");
  });

  it("marks a feature page's sub-route as current, and '/' only on '/'", () => {
    renderNav("/replay/run-1");
    expect(screen.getByRole("link", { name: "Replay" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Live Twin" })).not.toHaveAttribute("aria-current");
  });

  it("reserves page space while mounted and releases it on unmount", () => {
    const { unmount } = renderNav();
    expect(document.documentElement.dataset.mobileNav).toBe("1");
    unmount();
    expect(document.documentElement.dataset.mobileNav).toBeUndefined();
  });

  it("renders nothing when signed out, and nothing (no throw) outside a Router", () => {
    status = "signed-out";
    renderNav();
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
    status = "signed-in";
    render(<MobileBottomNav registry={registry} />);
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
  });
});

describe("DashboardSidebar accessibility", () => {
  const cfg: SimConfig = { serverUtil: 55, outsideTemp: 20, waterStress: 0.3, chilledWaterSetpoint: 7, coolingMode: "Auto", aiOptimizer: false };
  const renderSidebar = (collapsed: boolean, onToggle = vi.fn()) => {
    render(
      <MemoryRouter>
        <DashboardSidebar config={cfg} onChange={vi.fn()} onRunSim={vi.fn()} simRunning={false} collapsed={collapsed} onToggle={onToggle} />
      </MemoryRouter>,
    );
    return onToggle;
  };
  const setWidth = (w: number) => Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: w });
  afterEach(() => setWidth(1024));

  it("the collapse control has a name and reports expanded state", () => {
    const onToggle = renderSidebar(false);
    const btn = screen.getByRole("button", { name: "Collapse controls sidebar" });
    expect(btn).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("when collapsed the control says Expand and every setting still has a name", () => {
    renderSidebar(true);
    expect(screen.getByRole("button", { name: "Expand controls sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("img", { name: "Server Utilisation: 55%" })).toBeInTheDocument();
  });

  it("every slider and the cooling-mode select has an accessible name", () => {
    renderSidebar(false);
    for (const name of ["Server Utilisation", "Outside Temperature", "Water Stress Index", "Chilled Water Setpoint"]) {
      expect(screen.getByRole("slider", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("combobox", { name: "Cooling mode" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Simulation controls" })).toBeInTheDocument();
  });

  it("on a phone an open sidebar is an overlay: backdrop click and Escape both close it", () => {
    setWidth(360);
    const onToggle = renderSidebar(false);
    fireEvent.click(screen.getByTestId("sidebar-backdrop"));
    expect(onToggle).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("on a desktop width there is no backdrop and Escape does nothing", () => {
    setWidth(1280);
    const onToggle = renderSidebar(false);
    expect(screen.queryByTestId("sidebar-backdrop")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onToggle).not.toHaveBeenCalled();
  });
});
