import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  role: "operator" as string,
  username: "operator1",
  passport: undefined as unknown,
  fetchOptimized: vi.fn(),
  fetchRecommendation: vi.fn(),
  fetchSandbox: vi.fn(),
  fetchProposals: vi.fn(),
  createProposal: vi.fn(),
  decideProposal: vi.fn(),
  fetchShadowSummary: vi.fn(),
  postShadowSample: vi.fn(),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role: mocks.role, username: mocks.username }) }));
vi.mock("@/hooks/simulationContext", () => ({
  useSharedSimulation: () => ({ config: { serverUtil: 65, outsideTemp: 22, waterStress: 0.1, coolingMode: "Auto", chilledWaterSetpoint: 10 } }),
}));
vi.mock("@/telemetry/useFeed", () => ({ useFeed: () => null }));
vi.mock("@/features/explainability/usePassport", () => ({
  usePassport: () => ({ query: { data: mocks.passport, isError: false } }),
}));
vi.mock("@/api/apiClient", async (orig) => ({ ...(await orig<typeof import("@/api/apiClient")>()), fetchOptimized: mocks.fetchOptimized }));
vi.mock("./api", async (orig) => ({
  ...(await orig<typeof import("./api")>()),
  fetchRecommendation: mocks.fetchRecommendation,
  fetchSandbox: mocks.fetchSandbox,
  fetchProposals: mocks.fetchProposals,
  createProposal: mocks.createProposal,
  decideProposal: mocks.decideProposal,
  fetchShadowSummary: mocks.fetchShadowSummary,
  postShadowSample: mocks.postShadowSample,
}));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import OptimizerPage from "./OptimizerPage";
import { EFFECT, RECOMMENDATION, passport, proposal } from "./testFixtures";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OptimizerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.role = "operator";
  mocks.username = "operator1";
  mocks.passport = passport({ outcome: "NOT_EVALUATED", loadable: false });
  mocks.fetchOptimized.mockReset();
  mocks.fetchRecommendation.mockReset().mockResolvedValue(RECOMMENDATION);
  mocks.fetchSandbox.mockReset().mockResolvedValue({ predicted: { ...EFFECT, proposed: { ...EFFECT.proposed, mean_pue: 1.35 } }, persisted: false });
  mocks.fetchProposals.mockReset().mockResolvedValue([proposal()]);
  mocks.createProposal.mockReset().mockResolvedValue(proposal({ id: 2 }));
  mocks.decideProposal.mockReset().mockImplementation(async (id: number, d: string) => proposal({ id, status: d === "approve" ? "approved" : "rejected", decided_by: "admin1" }));
  mocks.fetchShadowSummary.mockReset().mockResolvedValue({ n_samples: 8, agreement_rate: 0.75 });
  mocks.postShadowSample.mockReset().mockResolvedValue({});
});
afterEach(cleanup);

describe("PPO unavailable (503)", () => {
  it("shows the reason, says nothing was run, and the baseline recommendation is on the page", async () => {
    mocks.fetchOptimized.mockRejectedValue(new ApiError({ kind: "unavailable", status: 503, code: "model_unavailable" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Request a PPO run/ }));
    const box = await screen.findByTestId("ppo-unavailable");
    expect(box).toHaveTextContent("not available");
    expect(box).toHaveTextContent("503 model_unavailable");
    expect(box).toHaveTextContent("quarantined: no promoted policy"); // the registry's own reason
    expect(box).toHaveTextContent("Nothing was run");
    expect(screen.queryByTestId("ppo-result")).toBeNull();
    expect(await screen.findByTestId("recommendation-source")).toHaveTextContent("PID baseline controller");
    expect(screen.getByText(/The PPO optimizer is unavailable, so this is the recommendation shown/)).toBeInTheDocument();
  });

  it("a different failure is not presented as 'unavailable'", async () => {
    mocks.fetchOptimized.mockRejectedValue(new ApiError({ kind: "rate_limited", status: 429 }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Request a PPO run/ }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("ppo-unavailable")).toBeNull();
  });

  it("an empty registry already says the optimizer is unavailable, before any request", async () => {
    renderPage();
    expect(await screen.findByTestId("ppo-registry")).toHaveTextContent("No promoted PPO policy");
    expect(await screen.findByText(/The PPO optimizer is unavailable, so this is the recommendation shown/)).toBeInTheDocument();
  });

  it("a successful run shows simulator numbers labelled as unevaluated and offers no proposal from it", async () => {
    mocks.passport = passport({ loadable: true });
    mocks.fetchOptimized.mockResolvedValue({
      results: [],
      summary: { mean_pue: 1.31, mean_wue: 0.5, mean_cooling_power_kw: 120, total_water_consumed_L: 900, safety_violations: 0 },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Request a PPO run/ }));
    const result = await screen.findByTestId("ppo-result");
    expect(result).toHaveTextContent("no evaluation status");
    expect(result).toHaveTextContent("1.310");
  });
});

describe("claim text gating", () => {
  it("without outcome A no claim that PPO beats the baselines appears anywhere", async () => {
    mocks.passport = passport({ outcome: "B", claim: "PPO beats the baselines by 20%" });
    renderPage();
    const gate = await screen.findByTestId("claim-gate");
    expect(gate).toHaveAttribute("data-allowed", "no");
    expect(gate).toHaveTextContent("No claim is made that PPO outperforms the baselines");
    expect(screen.queryByText(/beats the baselines/)).toBeNull();
    expect(screen.queryByTestId("claim-text")).toBeNull();
  });

  it("with outcome A only the stored claim text is shown, verbatim", async () => {
    const text = "Stored claim: the criterion in report ev-1 was met on the simulated scenarios.";
    mocks.passport = passport({ outcome: "A", claim: text, loadable: true });
    renderPage();
    const el = await screen.findByTestId("claim-text");
    expect(el.textContent).toBe(text);
    expect(screen.getByTestId("claim-gate")).toHaveAttribute("data-allowed", "yes");
  });
});

describe("recommendation, sandbox and proposing", () => {
  it("shows the controller, its basis, the stored-reward ranking note, the predicted effect and why rule was not used", async () => {
    renderPage();
    expect(await screen.findByTestId("recommendation-source")).toHaveTextContent("12.0 °C chilled water and Hybrid cooling");
    expect(screen.getByText(/not an evaluation on this facility and not a comparison with PPO/)).toBeInTheDocument();
    const card = within(screen.getByRole("region", { name: "Baseline controller recommendation" }));
    expect(card.getByTestId("effect-table")).toHaveTextContent("model estimate on simulated data");
    expect(card.getByRole("row", { name: /Mean PUE/ })).toHaveTextContent("−0.100 (lower)");
    expect(screen.getByText(/rule not used: tuned against different code/)).toBeInTheDocument();
  });

  it("the sandbox runs with the edited set-points and saves nothing", async () => {
    renderPage();
    await screen.findByTestId("recommendation-source");
    fireEvent.change(screen.getByLabelText(/Chilled water/), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText(/Cooling mode/), { target: { value: "free_air" } });
    fireEvent.click(screen.getByRole("button", { name: "Run in sandbox" }));
    await waitFor(() => expect(mocks.fetchSandbox).toHaveBeenCalledTimes(1));
    expect(mocks.fetchSandbox.mock.calls[0][1]).toEqual({ chilled_water_temp_c: 9, cooling_mode: "free_air" });
    expect(await screen.findByText(/Sandbox result/)).toBeInTheDocument();
    expect(mocks.createProposal).not.toHaveBeenCalled();
    expect(screen.getByText(/recorded as manual/)).toBeInTheDocument();
  });

  it("an out-of-range set-point blocks both buttons", async () => {
    renderPage();
    await screen.findByTestId("recommendation-source");
    fireEvent.change(screen.getByLabelText(/Chilled water/), { target: { value: "30" } });
    expect(screen.getByRole("button", { name: "Run in sandbox" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Propose for approval" })).toBeDisabled();
  });

  it("an operator proposes: the request carries the set-points and the page says it is waiting for an admin", async () => {
    renderPage();
    await screen.findByTestId("recommendation-source");
    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: " cheaper " } });
    fireEvent.click(screen.getByRole("button", { name: "Propose for approval" }));
    await waitFor(() => expect(mocks.createProposal).toHaveBeenCalledTimes(1));
    expect(mocks.createProposal.mock.calls[0][0]).toMatchObject({ chilled_water_temp_c: 12, cooling_mode: "hybrid", rationale: "cheaper", current_mode: "auto" });
    expect(await screen.findByText("Proposal #2 is waiting for an admin's decision.")).toBeInTheDocument();
  });

  it("a server refusal (422) is shown in plain words", async () => {
    mocks.createProposal.mockRejectedValue(new ApiError({ kind: "validation", status: 422, code: "unsafe_prediction" }));
    renderPage();
    await screen.findByTestId("recommendation-source");
    fireEvent.click(screen.getByRole("button", { name: "Propose for approval" }));
    expect(await screen.findByText(/would exceed its limit/)).toBeInTheDocument();
  });

  it("a viewer can read and use the sandbox but cannot propose", async () => {
    mocks.role = "viewer";
    renderPage();
    await screen.findByTestId("recommendation-source");
    expect(screen.queryByRole("button", { name: "Propose for approval" })).toBeNull();
    expect(screen.getByText(/Proposing needs the operator role/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run in sandbox" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Request a PPO run/ })).toBeNull();
  });

  it("when no baseline is usable it says so and lists the reasons instead of inventing a recommendation", async () => {
    mocks.fetchRecommendation.mockResolvedValue({
      recommendation: { selected: null, considered: [{ name: "pid", usable: false, reason: "the config is missing or malformed", validation_reward: null, status: null }], note: "n" },
      predicted: null,
      persisted: false,
    });
    renderPage();
    const box = await screen.findByTestId("no-baseline");
    expect(box).toHaveTextContent("No baseline controller can make a recommendation");
    expect(box).toHaveTextContent("pid: the config is missing or malformed");
    expect(screen.queryByRole("button", { name: "Propose for approval" })).toBeNull();
  });
});

describe("approval flow by role", () => {
  it("an operator sees the proposals but no approve or reject buttons", async () => {
    renderPage();
    expect(await screen.findByTestId("proposal")).toHaveTextContent("Pending");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("a different admin approves with a note; the row updates from the server's answer", async () => {
    mocks.role = "admin";
    mocks.username = "admin1";
    renderPage();
    const row = await screen.findByTestId("proposal");
    fireEvent.change(within(row).getByLabelText(/Note/), { target: { value: "ok" } });
    fireEvent.click(within(row).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(mocks.decideProposal).toHaveBeenCalledWith(1, "approve", "ok"));
    await waitFor(() => expect(within(screen.getByTestId("proposal")).getByTestId("proposal-status")).toHaveTextContent("Approved"));
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("an admin can reject", async () => {
    mocks.role = "admin";
    mocks.username = "admin1";
    renderPage();
    fireEvent.click(within(await screen.findByTestId("proposal")).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(mocks.decideProposal).toHaveBeenCalledWith(1, "reject", ""));
  });

  it("an admin cannot decide their own proposal: no buttons, with the reason", async () => {
    mocks.role = "admin";
    mocks.username = "admin1";
    mocks.fetchProposals.mockResolvedValue([proposal({ proposer: "admin1" })]);
    renderPage();
    const row = await screen.findByTestId("proposal");
    expect(within(row).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(row).toHaveTextContent("someone else must decide it");
  });

  it("a conflict from the server (already decided elsewhere) is explained", async () => {
    mocks.role = "admin";
    mocks.username = "admin1";
    mocks.decideProposal.mockRejectedValue(new ApiError({ kind: "conflict", status: 409, code: "not_pending" }));
    renderPage();
    fireEvent.click(within(await screen.findByTestId("proposal")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/already decided/)).toBeInTheDocument();
  });

  it("decided proposals show who decided and the approval is described as a record only", async () => {
    mocks.fetchProposals.mockResolvedValue([proposal({ status: "approved", decided_by: "admin1", decision_note: "fine" })]);
    renderPage();
    const row = await screen.findByTestId("proposal");
    expect(row).toHaveTextContent("Approved by admin1: fine");
    expect(screen.getByText(/does not apply setpoints to any equipment/)).toBeInTheDocument();
  });
});

describe("shadow-mode comparison", () => {
  it("draws the agreement chart with a text alternative and says what is being compared", async () => {
    renderPage();
    const chart = await screen.findByTestId("shadow-chart");
    expect(within(chart).getByRole("img")).toHaveAccessibleName(/chose the same cooling mode in 6 \(75\.0%\) and a different one in 2/);
    expect(chart).toHaveTextContent("Same cooling mode in 6 of 8 samples (75.0%). Different in 2.");
    expect(screen.getByText(/Agreement does not mean either is better/)).toBeInTheDocument();
  });

  it("with no samples it says so instead of drawing a chart", async () => {
    mocks.fetchShadowSummary.mockResolvedValue({ n_samples: 0, agreement_rate: null, message: "No shadow samples yet" });
    renderPage();
    expect(await screen.findByTestId("shadow-empty")).toHaveTextContent("No shadow samples yet");
    expect(screen.queryByTestId("shadow-chart")).toBeNull();
  });

  it("recording a sample while no policy exists reports the 503 plainly", async () => {
    mocks.postShadowSample.mockRejectedValue(new ApiError({ kind: "unavailable", status: 503, code: "model_unavailable" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Record a shadow sample" }));
    expect(await screen.findByText(/there is no policy to shadow/)).toBeInTheDocument();
  });
});
