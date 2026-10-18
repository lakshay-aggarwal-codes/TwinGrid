// Deliberately NO mock of RotateLink and NO <RotateTransition>: this is how the nav is mounted in the real app
// (AuthGate > AccountMenu > settings slot, outside the transition provider). It once crashed there.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Boxes } from "lucide-react";
import { createFeatureRegistry } from "../registry";
import type { FeatureModule } from "../types";

vi.mock("@/hooks/useAuth.ts", () => ({
  useAuth: () => ({ status: "signed-in" }),
  useRole: () => ({ role: "viewer" }),
}));

import { MobileBottomNav } from "./MobileBottomNav";

const feature: FeatureModule = {
  id: "demo",
  route: { path: "/replay", component: () => null },
  nav: { label: "Replay", icon: Boxes, group: "Operate", order: 1 },
};
const registry = createFeatureRegistry([feature], { onReject: () => undefined });

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

describe("MobileBottomNav outside <RotateTransition>", () => {
  it("renders without throwing and every item is a real link", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <MobileBottomNav registry={registry} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual(["/", "/analytics", "/replay"]);
  });

  it("navigates when a link is pressed", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <MobileBottomNav registry={registry} />
        <Where />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/");
    fireEvent.click(screen.getByRole("link", { name: "Analytics" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/analytics");
    expect(screen.getByRole("link", { name: "Analytics" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("link", { name: "Replay" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/replay");
  });
});
