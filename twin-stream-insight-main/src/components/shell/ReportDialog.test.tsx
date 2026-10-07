import { beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const esg = vi.hoisted(() => ({ fetchEsgReportPdf: vi.fn() }));
vi.mock("@/api/esgReport", () => ({ fetchEsgReportPdf: esg.fetchEsgReportPdf }));

import { ApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { FeedStoreContext } from "@/telemetry/useFeed";
import type { FeedStore, FeedView } from "@/telemetry/feedStore";
import { buildOperationalReport, buildSustainabilityReport } from "@/reports/reports";
import { captureIn } from "@/reports/reportFixtures";
import type { FreshnessState } from "@/telemetry/freshness";
import { ReportDialog } from "./ReportDialog";

beforeAll(() => {
  // jsdom lacks these; Radix Dialog does not need them but the object URL path does.
  if (!URL.createObjectURL) URL.createObjectURL = () => "blob:x";
  if (!URL.revokeObjectURL) URL.revokeObjectURL = () => {};
});

function storeIn(state: FreshnessState): FeedStore {
  const { feed } = captureIn(state);
  const view = { transport: { socket: "open", detail: null }, frame: feed.frame, receivedAtMonotonic: 1000, seqState: {}, freshness: feed.freshness } as unknown as FeedView;
  return { getView: () => view } as unknown as FeedStore;
}

const wrap = (state: FreshnessState | null, ui: ReactNode) =>
  state ? <FeedStoreContext.Provider value={storeIn(state)}>{ui}</FeedStoreContext.Provider> : ui;

// A report built the way the panels build it today: bare live state, no capture.
const bareOperational = () => buildOperationalReport({ liveState: captureIn("live").liveState, latestAnomaly: null, optimizeSummary: null });

describe("ReportDialog provenance (FE-10)", () => {
  it("shows the Provenance section first and no currency warning for a live feed", () => {
    render(wrap("live", <ReportDialog report={bareOperational()} onClose={() => {}} />));
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings[0]).toBe("Provenance");
    expect(screen.queryByTestId("report-currency-warning")).toBeNull();
    expect(screen.getByText("Generated (browser time)")).toBeInTheDocument();
  });

  it.each([
    ["stale", /STALE: .*last update 42 s ago/],
    ["disconnected", /DISCONNECTED: .*last data 42 s ago/],
  ] as const)("a report generated while %s says so at the top, from the feed state at that moment", (state, re) => {
    render(wrap(state, <ReportDialog report={bareOperational()} onClose={() => {}} />));
    const warning = screen.getByTestId("report-currency-warning");
    expect(warning).toHaveTextContent(re);
    expect(warning.compareDocumentPosition(screen.getAllByRole("heading", { level: 3 })[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("without a feed store the report still opens and says the feed state was not captured", () => {
    render(<ReportDialog report={bareOperational()} onClose={() => {}} />);
    expect(screen.getByTestId("report-currency-warning")).toHaveTextContent(/not captured/);
  });

  it("closed dialog renders nothing", () => {
    render(<ReportDialog report={null} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("ReportDialog ESG PDF download", () => {
  const sustainability = () => buildSustainabilityReport(captureIn("live").liveState, captureIn("live").capture);

  it("is offered on the sustainability report only", () => {
    const { unmount } = render(<ReportDialog report={sustainability()} onClose={() => {}} />);
    expect(screen.getByRole("button", { name: /Download ESG report/ })).toBeInTheDocument();
    unmount();
    render(<ReportDialog report={bareOperational()} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /Download ESG report/ })).toBeNull();
  });

  it.each([
    [new ApiError({ kind: "forbidden", status: 403 }), "You do not have permission to do that."],
    [new ApiError({ kind: "unavailable", status: 503 }), "The service is unavailable. Try again later."],
    [new ApiError({ kind: "network" }), "Could not reach the server. Check your connection."],
    [new AuthRequiredError(), "Your session has ended. Please sign in again."],
  ])("failure %# shows client-chosen text in an alert", async (error, text) => {
    esg.fetchEsgReportPdf.mockRejectedValueOnce(error);
    render(<ReportDialog report={sustainability()} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Download ESG report/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text);
    expect(alert).toHaveAttribute("data-testid", "esg-error");
  });

  it("a successful download shows no error", async () => {
    esg.fetchEsgReportPdf.mockResolvedValueOnce({ blob: new Blob(["%PDF"], { type: "application/pdf" }), filename: "twingrid-esg-report.pdf" });
    render(<ReportDialog report={sustainability()} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Download ESG report/ }));
    await waitFor(() => expect(esg.fetchEsgReportPdf).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("esg-error")).toBeNull());
  });
});
