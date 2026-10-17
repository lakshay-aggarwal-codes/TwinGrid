import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";

const { fetchFleet } = vi.hoisted(() => ({ fetchFleet: vi.fn() }));
vi.mock("./api", () => ({ fetchFleet }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import FleetPage from "./FleetPage";
import feature from "./index";
import { FLEET } from "./testFixtures";
import { getSite, setSite } from "./model";

function Probe() {
  const { search } = useLocation();
  return <output data-testid="search">{search}</output>;
}
const renderAt = (url = "/fleet") => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <FleetPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};
const order = () => within(screen.getByRole("list", { name: "Simulated sites" })).getAllByRole("button").map((b) => b.getAttribute("data-testid"));

beforeEach(() => {
  setSite(null);
  fetchFleet.mockReset().mockResolvedValue(FLEET);
});
afterEach(cleanup);

describe("fleet view", () => {
  it("shows five sites, each marked simulated, with the label and the carbon caveat", async () => {
    renderAt();
    await screen.findByTestId("site-sim-a");
    expect(order()).toHaveLength(5);
    expect(screen.getAllByText("Simulated")).toHaveLength(5);
    expect(screen.getByText(/Not real facilities/)).toBeInTheDocument();
    expect(screen.getByTestId("carbon-note")).toHaveTextContent("flat assumed grid intensity");
    expect(screen.getByRole("heading", { name: "Fleet view" })).toBeInTheDocument();
  });

  it("starts in overall order and re-sorts, with the rank shown for the chosen key", async () => {
    renderAt();
    await screen.findByTestId("site-sim-a");
    expect(order()).toEqual(["site-sim-a", "site-sim-d", "site-sim-c", "site-sim-e", "site-sim-b"]);
    fireEvent.click(screen.getByRole("button", { name: "Carbon" }));
    expect(order()[0]).toBe("site-sim-b");
    expect(screen.getByTestId("rank-sim-b")).toHaveTextContent("Rank 1 of 5");
    fireEvent.click(screen.getByRole("button", { name: "PUE" }));
    expect(order()).toEqual(["site-sim-a", "site-sim-d", "site-sim-c", "site-sim-b", "site-sim-e"]);
    expect(screen.getByRole("button", { name: "PUE" })).toHaveAttribute("aria-pressed", "true");
  });

  it("drill-down: selecting a site shows its detail, sets the site context and the address; selecting another switches", async () => {
    renderAt();
    await screen.findByTestId("site-sim-a");
    expect(screen.queryByTestId("site-detail")).toBeNull();
    fireEvent.click(screen.getByTestId("site-sim-b"));
    expect(screen.getByTestId("site-detail")).toHaveTextContent("Simulated site 2");
    expect(screen.getByTestId("site-detail")).toHaveTextContent("drought_override");
    expect(getSite()).toBe("sim-b");
    expect(screen.getByTestId("search")).toHaveTextContent("?site=sim-b");
    expect(screen.getByTestId("site-sim-b")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("site-sim-d"));
    expect(screen.getByTestId("site-detail")).toHaveTextContent("Simulated site 4");
    expect(screen.getByTestId("site-detail")).toHaveTextContent("None");
    expect(getSite()).toBe("sim-d");
    expect(screen.getByRole("link", { name: "Open in the What-if lab" })).toHaveAttribute("href", expect.stringMatching(/^\/whatif-lab\?load=\d+&amb=/));
  });

  it("a link with ?site= reopens that site, and an unknown site is ignored", async () => {
    renderAt("/fleet?site=sim-c");
    await screen.findByTestId("site-detail");
    expect(screen.getByTestId("site-detail")).toHaveTextContent("Simulated site 3");
    cleanup();
    setSite(null);
    renderAt("/fleet?site=bogus");
    await screen.findByTestId("site-sim-a");
    expect(screen.queryByTestId("site-detail")).toBeNull();
  });

  it("shows a loading skeleton, then a plain error with a working Try again", async () => {
    fetchFleet.mockReset().mockRejectedValueOnce(new ApiError({ kind: "network" })).mockResolvedValue(FLEET);
    renderAt();
    expect(screen.getAllByRole("status").some((el) => el.getAttribute("aria-busy") === "true")).toBe(true);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("site-sim-a")).toBeInTheDocument());
    expect(fetchFleet).toHaveBeenCalledTimes(2);
  });

  it("is a viewer-level Explore page at /fleet", () => {
    expect(feature.id).toBe("fleet-view");
    expect(feature.route?.path).toBe("/fleet");
    expect(feature.nav).toMatchObject({ group: "Explore", minRole: "viewer" });
  });
});
