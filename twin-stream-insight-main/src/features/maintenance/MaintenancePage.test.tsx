import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchMaintenanceHealth: vi.fn(),
  fetchWorkOrders: vi.fn(),
  createWorkOrder: vi.fn(),
  changeWorkOrderStatus: vi.fn(),
  fetchInbox: vi.fn(),
  fetchEquipmentHealth: vi.fn(),
  isOperator: true,
}));
vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()),
  fetchMaintenanceHealth: mocks.fetchMaintenanceHealth,
  fetchWorkOrders: mocks.fetchWorkOrders,
  createWorkOrder: mocks.createWorkOrder,
  changeWorkOrderStatus: mocks.changeWorkOrderStatus,
}));
vi.mock("../alerts-centre/api", async (orig) => ({ ...(await orig<typeof import("../alerts-centre/api")>()), fetchInbox: mocks.fetchInbox }));
vi.mock("@/api/apiClient", () => ({ fetchEquipmentHealth: mocks.fetchEquipmentHealth }));
vi.mock("@/hooks/useAuth", () => ({
  useRole: () => ({ isOperator: mocks.isOperator, role: mocks.isOperator ? "operator" : "viewer" }),
  useAuth: () => ({ username: "op1", role: mocks.isOperator ? "operator" : "viewer" }),
}));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import { alertRow } from "../alerts-centre/testFixtures";
import MaintenancePage from "./MaintenancePage";
import { health, order } from "./testFixtures";

const ALERTS = [alertRow({ id: 3, severity: "CRITICAL", message: "Critical thermal excursion" }), alertRow({ id: 2, message: "Warning drift" })];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MaintenancePage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.isOperator = true;
  mocks.fetchMaintenanceHealth.mockReset().mockResolvedValue(health());
  mocks.fetchWorkOrders.mockReset().mockResolvedValue([order()]);
  mocks.createWorkOrder.mockReset().mockResolvedValue(order({ id: 8, title: "Created one" }));
  mocks.changeWorkOrderStatus.mockReset().mockResolvedValue(order({ status: "in_progress", next_statuses: ["open", "done", "cancelled"] }));
  mocks.fetchInbox.mockReset().mockResolvedValue(ALERTS);
  mocks.fetchEquipmentHealth.mockReset().mockResolvedValue({ available: false, message: "No predictive-maintenance training run found." });
});
afterEach(cleanup);

describe("health", () => {
  it("shows per-asset health with a glyph and a word, the trend in words, and no remaining-life number", async () => {
    renderPage();
    const row = await screen.findByTestId("health-row-facility-level");
    expect(row).toHaveTextContent("■");
    expect(row).toHaveTextContent("warning");
    expect(row).toHaveTextContent("it_power_kw");
    expect(row).toHaveTextContent("Trend: up 39.0 kW over 3.3 h (39% of the valid range).");
    expect(within(row).getByRole("img", { name: /it_power_kw trend over the last 24 hours/ })).toBeInTheDocument();
    expect(screen.getByTestId("health-label")).toHaveTextContent("not a failure prediction");
    expect(screen.getByTestId("remaining-life")).toHaveTextContent("Remaining life: not available.");
    expect(screen.getByTestId("health-counts")).toHaveTextContent("1 warning, 0 watch, 0 ok, 2 not measured");
  });

  it("lists assets without a sensor as NOT MEASURED instead of as healthy", async () => {
    renderPage();
    const d = await screen.findByTestId("not-measured");
    expect(d).toHaveTextContent("2 assets have no sensor: health NOT MEASURED");
    expect(screen.queryByTestId("health-row-rack-1")).toBeNull();
  });

  it("shows an error state, not an empty table, when health cannot be read", async () => {
    mocks.fetchMaintenanceHealth.mockReset().mockRejectedValue(new ApiError({ kind: "server" }));
    renderPage();
    await waitFor(() => expect(screen.queryByText("Reading stored telemetry…")).toBeNull());
    expect(screen.queryByTestId("health-table")).toBeNull();
    expect(screen.queryByTestId("health-counts")).toBeNull();
  });

  it("shows the existing model's methodology as such, or says it is not available", async () => {
    mocks.fetchEquipmentHealth.mockReset().mockResolvedValue({
      available: true,
      baseline: { mae: 40.2, rmse: 50, r2: 0.1 },
      lstm: { mae: 20.4, rmse: 28, r2: 0.7 },
      beats_baseline: true,
      dataset_caveat: "Trained on NASA C-MAPSS, a proxy dataset.",
    });
    renderPage();
    expect(await screen.findByTestId("model-metrics")).toHaveTextContent("baseline 40.2, LSTM 20.4 (LSTM better)");
    expect(screen.getByTestId("model-caveat")).toHaveTextContent("NASA C-MAPSS");
    expect(screen.getByTestId("model-context")).toHaveTextContent("not applied to the assets above");
    cleanup();
    mocks.fetchEquipmentHealth.mockReset().mockResolvedValue({ available: false });
    renderPage();
    expect(await screen.findByTestId("model-unavailable")).toHaveTextContent("NOT MEASURED");
  });
});

describe("creating a work order", () => {
  it("from a health warning: the row prefills the form and the server gets the asset and sensor", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("create-from-facility-level"));
    expect(screen.getByLabelText("From a health warning")).toBeChecked();
    expect(screen.getByLabelText("Asset")).toHaveValue("facility-level");
    expect(screen.getByLabelText("Sensor (optional)")).toHaveValue("it_power_kw");
    expect(screen.getByLabelText("Priority")).toHaveValue("high");
    fireEvent.click(screen.getByTestId("create-submit"));
    await waitFor(() => expect(mocks.createWorkOrder).toHaveBeenCalledTimes(1));
    expect(mocks.createWorkOrder.mock.calls[0][0]).toEqual({
      priority: "high",
      asset_external_id: "facility-level",
      source: { kind: "health", measurand: "it_power_kw" },
    });
    expect(await screen.findByTestId("create-done")).toHaveTextContent("Work order #8 created (Created one).");
    expect(screen.getByLabelText("By hand")).toBeChecked(); // the form was reset
  });

  it("from an alert: the inbox is offered and the server gets the alert id", async () => {
    renderPage();
    await screen.findByTestId("create-form");
    fireEvent.click(screen.getByLabelText("From an alert"));
    const select = screen.getByLabelText("Alert");
    await waitFor(() => expect(within(select).getByText(/#3 · CRITICAL · Critical thermal excursion/)).toBeInTheDocument());
    fireEvent.change(select, { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("create-submit"));
    await waitFor(() => expect(mocks.createWorkOrder).toHaveBeenCalledTimes(1));
    expect(mocks.createWorkOrder.mock.calls[0][0]).toEqual({ priority: "medium", source: { kind: "alert", alert_id: 3 } });
  });

  it("by hand: an empty title is named and nothing is sent; then a title is sent", async () => {
    renderPage();
    await screen.findByTestId("create-form");
    fireEvent.click(screen.getByTestId("create-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a title.");
    expect(mocks.createWorkOrder).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Replace filter" } });
    fireEvent.click(screen.getByTestId("create-submit"));
    await waitFor(() => expect(mocks.createWorkOrder).toHaveBeenCalledTimes(1));
    expect(mocks.createWorkOrder.mock.calls[0][0]).toEqual({ title: "Replace filter", priority: "medium", source: { kind: "manual" } });
  });

  it("choosing an alert or asset is required, and a missing choice is named", async () => {
    renderPage();
    await screen.findByTestId("create-form");
    fireEvent.click(screen.getByLabelText("From an alert"));
    fireEvent.click(screen.getByTestId("create-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an alert.");
    fireEvent.click(screen.getByLabelText("From a health warning"));
    fireEvent.click(screen.getByTestId("create-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an asset.");
    expect(mocks.createWorkOrder).not.toHaveBeenCalled();
  });

  it("a refused create shows fixed wording (never the server's text) and keeps the form", async () => {
    mocks.createWorkOrder.mockReset().mockRejectedValue(new ApiError({ kind: "forbidden", status: 403 }));
    renderPage();
    await screen.findByTestId("create-form");
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Replace filter" } });
    fireEvent.click(screen.getByTestId("create-submit"));
    expect(await screen.findByTestId("create-failed")).toHaveTextContent("Only operators can create or change work orders.");
    expect(screen.getByLabelText("Title")).toHaveValue("Replace filter");
  });

  it("a viewer can read health and orders but is offered no way to create or change one", async () => {
    mocks.isOperator = false;
    renderPage();
    expect(await screen.findByTestId("create-form-denied")).toHaveTextContent("Only operators can create work orders.");
    expect(screen.queryByTestId("create-submit")).toBeNull();
    expect(await screen.findByTestId("order-7")).toBeInTheDocument();
    expect(screen.queryByTestId("order-7-to-in_progress")).toBeNull();
    expect(screen.getByTestId("create-from-facility-level")).toBeDisabled();
  });
});

describe("status flow", () => {
  it("offers exactly the moves the server listed and sends the chosen one", async () => {
    renderPage();
    const row = await screen.findByTestId("order-7");
    expect(row).toHaveTextContent("from simulated health data");
    expect(within(row).getByTestId("order-7-to-in_progress")).toHaveTextContent("Start work");
    expect(within(row).getByTestId("order-7-to-cancelled")).toHaveTextContent("Cancel order");
    expect(within(row).queryByTestId("order-7-to-done")).toBeNull();
    fireEvent.click(within(row).getByTestId("order-7-to-in_progress"));
    await waitFor(() => expect(mocks.changeWorkOrderStatus).toHaveBeenCalledWith(7, "in_progress", null));
  });

  it("a final order offers no moves", async () => {
    mocks.fetchWorkOrders.mockReset().mockResolvedValue([order({ status: "done", next_statuses: [] })]);
    renderPage();
    const row = await screen.findByTestId("order-7");
    expect(row).toHaveAttribute("data-status", "done");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("a refused move shows fixed wording on that order", async () => {
    mocks.changeWorkOrderStatus.mockReset().mockRejectedValue(new ApiError({ kind: "conflict", status: 409 }));
    renderPage();
    fireEvent.click(await screen.findByTestId("order-7-to-in_progress"));
    expect(await screen.findByTestId("order-7-error")).toHaveTextContent("That change is no longer possible");
  });

  it("filters by status and shows an empty state in words", async () => {
    renderPage();
    await screen.findByTestId("order-7");
    mocks.fetchWorkOrders.mockResolvedValue([]);
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "done" } });
    expect(await screen.findByText("No work orders with that status.")).toBeInTheDocument();
    expect(mocks.fetchWorkOrders.mock.calls.at(-1)?.[0]).toBe("done");
  });

  it("says plainly that a work order is a record only", async () => {
    renderPage();
    expect(await screen.findByTestId("orders-panel")).toHaveTextContent("TwinGrid dispatches nothing and changes no equipment.");
  });
});

describe("registration", () => {
  it("is the /maintenance route in the Operate group", async () => {
    const feature = (await import("./index")).default;
    expect(feature.id).toBe("maintenance");
    expect(feature.route?.path).toBe("/maintenance");
    expect(feature.nav).toMatchObject({ label: "Maintenance", group: "Operate", minRole: "viewer" });
  });
});
