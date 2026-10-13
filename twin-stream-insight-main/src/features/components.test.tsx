import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import example from "@/test/fixtures/exampleFeature";
import { createFeatureRegistry } from "./registry";
import { Slot } from "./Slot";
import { FeatureNav } from "./FeatureNav";
import { featureRouteElements } from "./FeatureRoutes";
import type { FeatureModule } from "./types";

let currentRole: string | null = "viewer";
vi.mock("@/hooks/useAuth.ts", () => ({ useRole: () => ({ role: currentRole }) }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));
vi.mock("@/components/transition/RotateLink", () => ({
  RotateLink: ({ to, children, ...rest }: { to: string; children: ReactNode }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

const quiet = { onReject: () => undefined };

describe("<Slot>", () => {
  it("renders nothing (no wrapper) when no feature fills the slot", () => {
    const { container } = render(<Slot name="settings" registry={createFeatureRegistry([example], quiet)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders registered widgets and passes the host's context", async () => {
    render(<Slot name="facility-inspector" context={{ rackId: "rack-7" }} registry={createFeatureRegistry([example], quiet)} />);
    expect(await screen.findByTestId("example-widget")).toHaveTextContent("rack=rack-7");
  });

  it("isolates a throwing widget: it shows a notice and its sibling still renders", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Boom = () => {
      throw new Error("secret detail");
    };
    const Fine = () => <p>fine</p>;
    const registry = createFeatureRegistry(
      [
        { id: "boom", slots: [{ slot: "dashboard", component: Boom, order: 1 }] },
        { id: "fine", slots: [{ slot: "dashboard", component: Fine, order: 2 }] },
      ],
      quiet,
    );
    render(<Slot name="dashboard" registry={registry} />);
    expect(await screen.findByText("fine")).toBeInTheDocument();
    expect(screen.getByTestId("slot-widget-error")).toHaveTextContent("could not be shown");
    expect(screen.queryByText(/secret detail/)).toBeNull();
    err.mockRestore();
  });

  it("hides widgets the role may not use", () => {
    const Ops = () => <p>ops only</p>;
    const registry = createFeatureRegistry([{ id: "ops", slots: [{ slot: "dashboard", component: Ops, order: 1, minRole: "operator" }] }], quiet);
    currentRole = "viewer";
    const { container, rerender } = render(<Slot name="dashboard" registry={registry} />);
    expect(container).toBeEmptyDOMElement();
    currentRole = "operator";
    rerender(<Slot name="dashboard" registry={registry} />);
    expect(screen.getByText("ops only")).toBeInTheDocument();
    currentRole = "viewer";
  });
});

const nav = (minRole?: "operator") =>
  ({ ...example, id: "ex2", route: { path: "/ex2", component: () => null }, nav: { ...example.nav!, label: "Ops page", minRole }, slots: [] }) as FeatureModule;

describe("<FeatureNav>", () => {
  const renderNav = (registry: ReturnType<typeof createFeatureRegistry>, props: { collapsed?: boolean } = {}) =>
    render(
      <MemoryRouter initialEntries={["/example"]}>
        <FeatureNav orientation="vertical" registry={registry} {...props} />
      </MemoryRouter>,
    );

  it("renders nothing without features", () => {
    const { container } = renderNav(createFeatureRegistry([], quiet));
    expect(container).toBeEmptyDOMElement();
  });

  it("lists role-allowed links, marks the current page, and keeps accessible names when collapsed", () => {
    currentRole = "viewer";
    const registry = createFeatureRegistry([example, nav("operator")], quiet);
    const { unmount } = renderNav(registry);
    expect(screen.getByRole("navigation", { name: "Feature pages" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Example" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Ops page" })).toBeNull();
    unmount();

    currentRole = "operator";
    renderNav(registry, { collapsed: true });
    expect(screen.getByRole("link", { name: "Ops page" })).toHaveAttribute("href", "/ex2");
    expect(screen.queryByText("Ops page")).toBeNull(); // icon only, name still on the link
    currentRole = "viewer";
  });
});

describe("featureRouteElements", () => {
  const renderAt = (path: string, registry: ReturnType<typeof createFeatureRegistry>) =>
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          {featureRouteElements(registry)}
          <Route path="*" element={<p>core catch-all</p>} />
        </Routes>
      </MemoryRouter>,
    );

  it("serves a lazy feature page", async () => {
    currentRole = "viewer";
    renderAt("/example", createFeatureRegistry([example], quiet));
    expect(await screen.findByRole("heading", { name: "Example page" })).toBeInTheDocument();
  });

  it("shows the 404 page to a role that may not use the route, the page to one that may", async () => {
    const registry = createFeatureRegistry([nav("operator")], quiet);
    currentRole = "viewer";
    const first = renderAt("/ex2", registry);
    await waitFor(() => expect(screen.getByText("Oops! Page not found")).toBeInTheDocument());
    first.unmount();
    currentRole = "operator";
    const Page = () => <p>ops page body</p>;
    renderAt("/ex2", createFeatureRegistry([{ ...nav("operator"), route: { path: "/ex2", component: Page } }], quiet));
    expect(await screen.findByText("ops page body")).toBeInTheDocument();
    currentRole = "viewer";
  });

  it("leaves unknown paths to the core catch-all", () => {
    renderAt("/nothing", createFeatureRegistry([example], quiet));
    expect(screen.getByText("core catch-all")).toBeInTheDocument();
  });
});
