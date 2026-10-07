import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AlertRecord } from "@/api/apiClient";

const mocks = vi.hoisted(() => ({
  fetchAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
  role: { current: "operator" as "operator" | "viewer" | null },
}));

vi.mock("@/api/apiClient", async (orig) => ({ ...(await orig<typeof import("@/api/apiClient")>()), fetchAlerts: mocks.fetchAlerts }));
vi.mock("@/api/alerts", async (orig) => ({ ...(await orig<typeof import("@/api/alerts")>()), acknowledgeAlert: mocks.acknowledgeAlert }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role: mocks.role.current }) }));

import { ApiError } from "@/api/apiError";
import { alertRow } from "@/components/alerts/alertFixtures";
import { IncidentsPanel, REFRESH_INTERVAL_MS } from "./IncidentsPanel.tsx";

function setup(open = true, alerts: AlertRecord[] = [alertRow({ id: 2 }), alertRow({ id: 1, acknowledged: true, acknowledged_by: "alice", acknowledged_at: "2026-10-06T11:00:00Z" })]) {
  mocks.fetchAlerts.mockResolvedValue(alerts);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const ui = (o: boolean) => (
    <QueryClientProvider client={client}>
      <IncidentsPanel open={o} onClose={() => {}} onFocusFacility={() => {}} latestAnomaly={null} onGenerateReport={() => {}} />
    </QueryClientProvider>
  );
  const r = render(ui(open));
  return { ...r, rerenderOpen: (o: boolean) => r.rerender(ui(o)), client };
}

beforeEach(() => {
  mocks.fetchAlerts.mockReset();
  mocks.acknowledgeAlert.mockReset();
  mocks.role.current = "operator";
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
});

describe("IncidentsPanel list", () => {
  it("renders backend rows with lifecycle, severity text, origin, model version, and the detector-score wording", async () => {
    setup();
    const rows = await screen.findAllByRole("listitem", {}, { timeout: 2000 }).then((r) => r.filter((li) => li.hasAttribute("data-alert-id")));
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByTestId("lifecycle")).toHaveTextContent("New");
    expect(within(rows[1]).getByTestId("lifecycle")).toHaveTextContent("Acknowledged");
    expect(within(rows[0]).getByText("WARNING")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Simulated")).toBeInTheDocument();
    fireEvent.click(within(rows[0]).getAllByRole("button")[0]);
    expect(within(rows[0]).getByText("Detector score")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/Detector score \(reconstruction error\): 0\.1234/)).toBeInTheDocument();
    expect(rows[0].textContent).not.toMatch(/\d%/);
    expect(within(rows[0]).getByText("v3")).toBeInTheDocument();
  });

  it("each row is a button with aria-expanded / aria-controls", async () => {
    setup();
    const li = (await screen.findAllByRole("listitem")).find((x) => x.hasAttribute("data-alert-id"))!;
    const toggle = within(li).getAllByRole("button")[0];
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).not.toBeNull();
  });

  it("keeps the 'facility-wide, no sensor attribution' notice unless attribution fields arrive", async () => {
    setup(true, [alertRow({ id: 1 }), { ...alertRow({ id: 2 }), sensor_reading_id: 9 } as AlertRecord]);
    const items = (await screen.findAllByRole("listitem")).filter((x) => x.hasAttribute("data-alert-id"));
    items.forEach((li) => fireEvent.click(within(li).getAllByRole("button")[0]));
    expect(within(items[0]).getByTestId("no-attribution")).toHaveTextContent(/no sensor attribution/);
    expect(within(items[1]).queryByTestId("no-attribution")).toBeNull();
    expect(within(items[1]).getByText("sensor_reading_id")).toBeInTheDocument();
  });

  it("labels a naive timestamp '(UTC assumed)' and leaves an offset one alone", async () => {
    setup(true, [alertRow({ id: 2, created_at: "2026-10-06T10:00:00" }), alertRow({ id: 1, created_at: "2026-10-06T10:00:00Z" })]);
    const times = await screen.findAllByTestId("alert-time");
    expect(times[0]).toHaveTextContent("2026-10-06 10:00:00 UTC (UTC assumed)");
    expect(times[1]).toHaveTextContent("2026-10-06 10:00:00 UTC");
    expect(times[1]).not.toHaveTextContent("assumed");
  });

  it("an unknown severity is a neutral badge with the raw text", async () => {
    setup(true, [alertRow({ id: 1, severity: "SEVERE" })]);
    const badge = await screen.findByText("SEVERE");
    expect(badge.closest("[data-severity]")).toHaveAttribute("data-severity", "unknown");
    expect(badge.closest("[data-severity]")!.className).toContain("bg-muted");
  });

  it("groups rows by dedupe_key with a detection count, without hiding any row", async () => {
    setup(true, [alertRow({ id: 3, dedupe_key: "ep" }), alertRow({ id: 2, dedupe_key: "ep" }), alertRow({ id: 1, dedupe_key: "ep" }), alertRow({ id: 4 })]);
    expect(await screen.findByTestId("episode-header")).toHaveTextContent("Episode · 3 detections");
    expect((await screen.findAllByRole("listitem")).filter((x) => x.hasAttribute("data-alert-id"))).toHaveLength(4);
  });

  it("shows the explicit empty state (not an error) and offers no snooze/resolve controls", async () => {
    setup(true, []);
    expect(await screen.findByText(/No alerts recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /snooze|resolve/i })).toBeNull();
  });

  it("never renders snooze or resolve controls on rows", async () => {
    setup();
    await screen.findAllByTestId("lifecycle");
    expect(screen.queryByRole("button", { name: /snooze|resolve/i })).toBeNull();
  });

  it("shows a safe error state (no backend text) when the list fails", async () => {
    mocks.fetchAlerts.mockRejectedValue(new ApiError({ kind: "server", status: 500 }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <IncidentsPanel open onClose={() => {}} onFocusFacility={() => {}} latestAnomaly={null} onGenerateReport={() => {}} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/could not complete the request/i)).toBeInTheDocument();
  });
});

describe("acknowledge", () => {
  const firstNewRow = async () => (await screen.findAllByRole("listitem")).find((x) => x.getAttribute("data-lifecycle") === "new")!;

  it("operator: pending first (row still New), then the SERVER's row replaces it", async () => {
    let resolve!: () => void;
    mocks.acknowledgeAlert.mockImplementation(() => new Promise<void>((r) => (resolve = r)));
    setup(true, [alertRow({ id: 2 })]);
    const row = await firstNewRow();
    fireEvent.click(within(row).getByRole("button", { name: "Acknowledge" }));
    // Pending: no optimistic success.
    expect(await within(row).findByText(/Acknowledging/)).toBeInTheDocument();
    expect(row).toHaveAttribute("data-lifecycle", "new");
    expect(mocks.acknowledgeAlert).toHaveBeenCalledWith(2);

    mocks.fetchAlerts.mockResolvedValue([alertRow({ id: 2, acknowledged: true, acknowledged_by: "bob", acknowledged_at: "2026-10-06T12:00:00Z" })]);
    await act(async () => resolve());
    await waitFor(() => expect(screen.getByTestId("lifecycle")).toHaveTextContent("Acknowledged"));
    fireEvent.click(screen.getAllByRole("button", { name: /Acknowledged/ })[0]);
    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).toBeNull();
  });

  it.each([
    [new ApiError({ kind: "forbidden", status: 403 }), "Your account does not have permission to do this."],
    [new ApiError({ kind: "not_found", status: 404 }), "The requested item was not found."],
    [new ApiError({ kind: "rate_limited", status: 429 }), "Too many requests were sent. Wait a moment, then try again."],
  ])("failure %# is shown in an alert with client-chosen text, and the row stays New", async (error, text) => {
    mocks.acknowledgeAlert.mockRejectedValue(error);
    setup(true, [alertRow({ id: 2 })]);
    const row = await firstNewRow();
    fireEvent.click(within(row).getByRole("button", { name: "Acknowledge" }));
    const alert = await within(row).findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(alert).toHaveTextContent("#2");
    expect(row).toHaveAttribute("data-lifecycle", "new");
  });

  it("viewer: sees state only -- a disabled control that says 'requires operator role'; nothing is sent", async () => {
    mocks.role.current = "viewer";
    setup(true, [alertRow({ id: 2 })]);
    const row = await firstNewRow();
    const btn = within(row).getByRole("button", { name: /requires operator role/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(mocks.acknowledgeAlert).not.toHaveBeenCalled();
    expect(within(row).queryByRole("button", { name: "Acknowledge" })).toBeNull();
  });

  it("an already-acknowledged row has no acknowledge control for anyone", async () => {
    setup(true, [alertRow({ id: 1, acknowledged: true, acknowledged_by: "alice", acknowledged_at: "2026-10-06T11:00:00Z" })]);
    await screen.findByTestId("lifecycle");
    expect(screen.queryByRole("button", { name: /^Acknowledge/ })).toBeNull();
  });
});

describe("polling", () => {
  it("polls every 15 s while open and visible", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    setup();
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    const base = mocks.fetchAlerts.mock.calls.length;
    expect(base).toBeGreaterThanOrEqual(1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS)));
    expect(mocks.fetchAlerts.mock.calls.length).toBe(base + 1);
    await act(async () => void (await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS)));
    expect(mocks.fetchAlerts.mock.calls.length).toBe(base + 2);
  });

  it("pauses when the panel is closed", async () => {
    vi.useFakeTimers();
    const { rerenderOpen } = setup();
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    rerenderOpen(false);
    const calls = mocks.fetchAlerts.mock.calls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 4)));
    expect(mocks.fetchAlerts.mock.calls.length).toBe(calls);
    expect(screen.queryByRole("complementary", { name: "Incidents" })).toBeNull();
  });

  it("never fetches while closed from the start", async () => {
    vi.useFakeTimers();
    setup(false);
    await act(async () => void (await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 3)));
    expect(mocks.fetchAlerts).not.toHaveBeenCalled();
  });

  it("pauses while the tab is hidden", async () => {
    vi.useFakeTimers();
    setup();
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    const calls = mocks.fetchAlerts.mock.calls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(REFRESH_INTERVAL_MS * 4)));
    expect(mocks.fetchAlerts.mock.calls.length).toBe(calls);
  });
});
