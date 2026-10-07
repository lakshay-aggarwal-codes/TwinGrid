import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";

const { fetchOptimized, auth } = vi.hoisted(() => ({ fetchOptimized: vi.fn(), auth: { role: "operator" as string | null } }));
vi.mock("@/api/apiClient", () => ({ fetchOptimized }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role: auth.role }) }));

import { OptimizationCard } from "./OptimizationCard";

const summary = { mean_pue: 1.3, mean_wue: 0.5, mean_cooling_power_kw: 20, total_water_consumed_L: 1000, total_reward: -12.34, safety_violations: 3 };

const start = async () => {
  fireEvent.click(screen.getByRole("button", { name: /Run policy in simulator/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
};

beforeEach(() => {
  fetchOptimized.mockReset();
  auth.role = "operator";
});

describe("OptimizationCard", () => {
  it("is headed 'Experimental · simulator-only · not evaluated'", () => {
    render(<OptimizationCard />);
    expect(screen.getByText("Experimental · simulator-only · not evaluated")).toBeInTheDocument();
  });

  it("a viewer sees the control disabled with 'Requires operator role', and nothing is requested", () => {
    auth.role = "viewer";
    render(<OptimizationCard />);
    expect(screen.getByRole("button", { name: /Run policy in simulator/ })).toBeDisabled();
    expect(screen.getByText("Requires operator role")).toBeInTheDocument();
    expect(fetchOptimized).not.toHaveBeenCalled();
  });

  it("asks for confirmation first; Cancel sends nothing", () => {
    render(<OptimizationCard />);
    fireEvent.click(screen.getByRole("button", { name: /Run policy in simulator/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchOptimized).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Run policy in simulator/ })).toBeInTheDocument();
  });

  it("while submitting shows only 'Waiting for response…' (no progress bar) and cannot be submitted twice", async () => {
    fetchOptimized.mockReturnValue(new Promise(() => {}));
    const { container } = render(<OptimizationCard />);
    await start();
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for response…");
    expect(container.querySelector('[role="progressbar"], progress')).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(fetchOptimized).toHaveBeenCalledTimes(1);
  });

  it("a completed result is neutral: no success/destructive colouring, relabelled objective value, not-evaluated note", async () => {
    fetchOptimized.mockResolvedValue({ results: [], summary, model_version: "ppo-3", experimental: true });
    const onSummary = vi.fn();
    const { container } = render(<OptimizationCard onSummaryChange={onSummary} />);
    await start();
    const result = await screen.findByTestId("optimize-result");
    expect(result).toHaveTextContent("Internal training objective value");
    expect(result).not.toHaveTextContent(/Total Reward/i);
    expect(result).toHaveTextContent("Safety violations (count reported by the run)");
    expect(result).toHaveTextContent("not evaluated, not compared with any baseline");
    expect(result).toHaveTextContent("Model version: ppo-3");
    expect(result).toHaveTextContent("Experimental: yes");
    expect(container.querySelector(".text-success, .text-destructive, .bg-success, .bg-destructive, [class*='text-green'], [class*='text-red']")).toBeNull();
    expect(container.textContent).not.toMatch(/optimi[sz]ed|recommend|\bsafe\b|AI/i);
    expect(onSummary).toHaveBeenLastCalledWith(summary);
    expect(result).toHaveAttribute("role", "status");
  });

  it.each([
    [new ApiError({ kind: "forbidden", status: 403 }), /permission/i],
    [new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 7 }), /Retry after 7 s/],
  ])("announces %# as an alert from the client's own copy", async (error, text) => {
    fetchOptimized.mockRejectedValue(error);
    render(<OptimizationCard />);
    await start();
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("503 model_unavailable is the unavailable-model state (a status, not an error alert)", async () => {
    fetchOptimized.mockRejectedValue(new ApiError({ kind: "unavailable", status: 503, code: "model_unavailable" }));
    render(<OptimizationCard />);
    await start();
    await waitFor(() => expect(screen.getByText("Model unavailable.")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("an unexpected failure never shows its message", async () => {
    fetchOptimized.mockRejectedValue(new Error("Traceback: db password"));
    const { container } = render(<OptimizationCard />);
    await start();
    await screen.findByRole("alert");
    expect(container).not.toHaveTextContent(/Traceback|password/);
  });

  it("'Run again' after a result returns to idle", async () => {
    fetchOptimized.mockResolvedValue({ results: [], summary });
    render(<OptimizationCard />);
    await start();
    fireEvent.click(await screen.findByRole("button", { name: "Run again" }));
    expect(screen.getByRole("button", { name: /Run policy in simulator/ })).toBeInTheDocument();
  });
});
