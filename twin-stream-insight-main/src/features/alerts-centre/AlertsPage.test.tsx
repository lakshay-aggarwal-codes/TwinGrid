import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchInbox: vi.fn(),
  fetchTimeline: vi.fn(),
  patchAlert: vi.fn(),
  isOperator: true,
}));
vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), fetchInbox: mocks.fetchInbox, fetchTimeline: mocks.fetchTimeline, patchAlert: mocks.patchAlert }));
vi.mock("@/hooks/useAuth", () => ({
  useRole: () => ({ isOperator: mocks.isOperator, role: mocks.isOperator ? "operator" : "viewer" }),
  useAuth: () => ({ username: "op1", role: mocks.isOperator ? "operator" : "viewer" }),
}));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import AlertsPage from "./AlertsPage";
import { alertRow, TIMELINE_1 } from "./testFixtures";

const ROWS = [
  alertRow({ id: 3, severity: "CRITICAL", message: "Critical thermal excursion" }),
  alertRow({ id: 2, severity: "WARNING", message: "Warning drift", status: "acknowledged", acknowledged: true, acknowledged_by: "op2", acknowledged_at: "2026-10-01T08:10:00+00:00" }),
  alertRow({ id: 1, severity: "INFO", message: "Info note", status: "resolved", resolved_by: "op2", resolved_at: "2026-10-01T08:20:00+00:00" }),
];

function Probe() {
  const { search } = useLocation();
  return <output data-testid="search">{search}</output>;
}
function renderAt(url = "/alerts") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AlertsPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const rows = () => screen.getAllByTestId("alert-row");

beforeEach(() => {
  window.localStorage.clear();
  mocks.isOperator = true;
  mocks.fetchInbox.mockReset().mockResolvedValue(ROWS);
  mocks.fetchTimeline.mockReset().mockResolvedValue(TIMELINE_1);
  mocks.patchAlert.mockReset().mockImplementation(async (id: number, body: { status?: string }) => ({ ...ROWS.find((r) => r.id === id)!, status: body.status ?? "open" }));
});
afterEach(cleanup);

describe("Alerts centre", () => {
  it("lists alerts with severity AND status as text, counts, and the data origin", async () => {
    renderAt();
    expect(await screen.findAllByTestId("alert-row")).toHaveLength(3);
    const first = rows()[0];
    expect(within(first).getByTestId("severity-badge")).toHaveTextContent("CRITICAL");
    expect(within(first).getByTestId("status-badge")).toHaveTextContent("Open");
    expect(within(first).getByText(/origin: simulated/)).toBeInTheDocument();
    expect(screen.getByTestId("alert-counts")).toHaveTextContent("1 open, 1 acknowledged, 1 resolved");
    expect(screen.getByTestId("alert-counts")).toHaveTextContent("1 open critical");
    expect(screen.getByRole("heading", { level: 1, name: "Alerts centre" })).toBeInTheDocument();
  });

  it("filters by severity and status, shows an empty-match message, and exposes the pressed state", async () => {
    renderAt();
    await screen.findAllByTestId("alert-row");
    const severity = within(screen.getByRole("group", { name: "Severity" }));
    const status = within(screen.getByRole("group", { name: "Status" }));
    const crit = severity.getByRole("button", { name: /CRITICAL/ });
    fireEvent.click(crit);
    expect(crit).toHaveAttribute("aria-pressed", "true");
    expect(rows()).toHaveLength(1);
    fireEvent.click(status.getByRole("button", { name: /Resolved/ }));
    expect(screen.getByTestId("no-matches")).toBeInTheDocument();
    fireEvent.click(crit);
    expect(rows()).toHaveLength(1);
    expect(within(rows()[0]).getByTestId("status-badge")).toHaveTextContent("Resolved");
  });

  it("selecting a row opens its details and timeline and records ?alert= in the URL", async () => {
    renderAt();
    await screen.findAllByTestId("alert-row");
    fireEvent.click(within(rows()[0]).getByRole("button", { name: /Critical thermal excursion/ }));
    const detail = await screen.findByTestId("alert-detail");
    expect(within(detail).getByRole("heading", { name: "Alert #3" })).toBeInTheDocument();
    expect(screen.getByTestId("search")).toHaveTextContent("?alert=3");
    expect(await within(detail).findByText("Alert raised by the detector")).toBeInTheDocument();
    expect(within(detail).getByText("Checked CRAC-02")).toBeInTheDocument();
    expect(mocks.fetchTimeline).toHaveBeenCalledWith(3, expect.anything());
  });

  it("a deep link opens the alert, with a facility link, an honest rack note and a Replay link at the alert's time", async () => {
    renderAt("/alerts?alert=2");
    const detail = await screen.findByTestId("alert-detail");
    expect(within(detail).getByRole("heading", { name: "Alert #2" })).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Open facility view" })).toHaveAttribute("href", "/");
    const replay = within(detail).getByRole("link", { name: "Open this moment in Replay" });
    expect(new URL(replay.getAttribute("href") as string, "http://x").searchParams.get("t")).toBe("2026-10-01T08:00:00Z");
    expect(within(detail).getByText(/does not attribute an alert to a rack/)).toBeInTheDocument();
  });

  it("an unknown ?alert= says so instead of showing nothing", async () => {
    renderAt("/alerts?alert=999");
    expect(await screen.findByText(/Alert 999 is not in the latest 200 alerts/)).toBeInTheDocument();
  });

  it("an operator acknowledges one alert: the request carries the status and the page shows the confirmation", async () => {
    renderAt("/alerts?alert=3");
    const detail = await screen.findByTestId("alert-detail");
    fireEvent.click(within(detail).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(mocks.patchAlert).toHaveBeenCalledWith(3, { status: "acknowledged" }));
    expect(await within(detail).findByText("Alert 3 is now acknowledged.")).toBeInTheDocument();
  });

  it("offers only the moves the lifecycle allows", async () => {
    renderAt("/alerts?alert=1"); // resolved
    const detail = await screen.findByTestId("alert-detail");
    expect(within(detail).getByRole("button", { name: "Re-open" })).toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(within(detail).queryByRole("button", { name: "Resolve" })).toBeNull();
  });

  it("assigns, unassigns and adds a note", async () => {
    mocks.patchAlert.mockImplementation(async (id: number, body: { assignee?: string | null }) => ({ ...ROWS.find((r) => r.id === id)!, assignee: body.assignee ?? null }));
    renderAt("/alerts?alert=3");
    const detail = await screen.findByTestId("alert-detail");
    fireEvent.change(within(detail).getByLabelText(/Assignee/), { target: { value: " op2 " } });
    fireEvent.click(within(detail).getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(mocks.patchAlert).toHaveBeenCalledWith(3, { assignee: "op2" }));
    fireEvent.click(within(detail).getByRole("button", { name: "Assign to me" }));
    await waitFor(() => expect(mocks.patchAlert).toHaveBeenCalledWith(3, { assignee: "op1" }));
    fireEvent.change(within(detail).getByLabelText(/Add a note/), { target: { value: "  looked at it " } });
    fireEvent.click(within(detail).getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(mocks.patchAlert).toHaveBeenCalledWith(3, { note: "looked at it" }));
    await waitFor(() => expect(within(detail).getByRole("button", { name: "Add note" })).toBeDisabled()); // the box was cleared
  });

  it("a 409 from the server is shown as plain text, not as the backend's message", async () => {
    mocks.patchAlert.mockRejectedValue(new ApiError({ kind: "conflict", status: 409 }));
    renderAt("/alerts?alert=3");
    const detail = await screen.findByTestId("alert-detail");
    fireEvent.click(within(detail).getByRole("button", { name: "Resolve" }));
    expect(await within(detail).findByRole("alert")).toHaveTextContent(/no longer possible/);
  });

  it("bulk acknowledge: selects only open alerts, sends one request each, reports the result", async () => {
    mocks.fetchInbox.mockResolvedValue([alertRow({ id: 5 }), alertRow({ id: 4 }), ...ROWS.slice(1)]);
    renderAt();
    await screen.findAllByTestId("alert-row");
    expect(screen.getByRole("checkbox", { name: /Select alert 2 / })).toBeDisabled(); // acknowledged
    fireEvent.click(screen.getByRole("button", { name: /Select open alerts/ }));
    const go = screen.getByRole("button", { name: "Acknowledge 2 selected" });
    fireEvent.click(go);
    await waitFor(() => expect(mocks.patchAlert).toHaveBeenCalledTimes(2));
    expect(mocks.patchAlert).toHaveBeenCalledWith(5, { status: "acknowledged" });
    expect(mocks.patchAlert).toHaveBeenCalledWith(4, { status: "acknowledged" });
    expect(await screen.findByText("2 acknowledged.")).toBeInTheDocument();
  });

  it("bulk acknowledge reports a partial failure", async () => {
    mocks.fetchInbox.mockResolvedValue([alertRow({ id: 5 }), alertRow({ id: 4 })]);
    mocks.patchAlert.mockImplementation(async (id: number) => {
      if (id === 5) throw new ApiError({ kind: "conflict", status: 409 });
      return alertRow({ id, status: "acknowledged" });
    });
    renderAt();
    await screen.findAllByTestId("alert-row");
    fireEvent.click(screen.getByRole("button", { name: /Select open alerts/ }));
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge 2 selected" }));
    expect(await screen.findByText("1 acknowledged, 1 failed.")).toBeInTheDocument();
  });

  it("a viewer can read everything but gets no change controls", async () => {
    mocks.isOperator = false;
    renderAt("/alerts?alert=3");
    const detail = await screen.findByTestId("alert-detail");
    expect(screen.queryByRole("checkbox", { name: /Select alert/ })).toBeNull();
    expect(screen.queryByRole("group", { name: "Bulk acknowledge" })).toBeNull();
    expect(within(detail).queryByRole("button", { name: "Acknowledge" })).toBeNull();
    expect(within(detail).getByText(/needs the operator role/)).toBeInTheDocument();
    expect(await within(detail).findByText("Alert raised by the detector")).toBeInTheDocument(); // the timeline still reads
  });

  it("the sound switch is off by default and remembers a change", async () => {
    renderAt();
    const sw = await screen.findByRole("checkbox", { name: /Play a sound/ });
    expect(sw).not.toBeChecked();
    fireEvent.click(sw);
    expect(window.localStorage.getItem("twingrid.alerts.sound")).toBe("on");
  });

  it("shows the empty, loading and error states", async () => {
    mocks.fetchInbox.mockResolvedValue([]);
    const { unmount } = renderAt();
    expect(await screen.findByText(/No alerts have been recorded yet/)).toBeInTheDocument();
    unmount();

    mocks.fetchInbox.mockRejectedValue(new ApiError({ kind: "server", status: 500 }));
    renderAt();
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
