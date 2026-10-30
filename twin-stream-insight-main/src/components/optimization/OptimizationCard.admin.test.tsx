import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchOptimized, auth } = vi.hoisted(() => ({ fetchOptimized: vi.fn(), auth: { role: "admin" as string | null } }));
vi.mock("@/api/apiClient", () => ({ fetchOptimized }));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role: auth.role }) }));

import { OptimizationCard } from "./OptimizationCard";

beforeEach(() => {
  fetchOptimized.mockReset();
});

describe("OptimizationCard for each role", () => {
  it.each(["admin", "operator"])("%s sees the control enabled, with no role note", (r) => {
    auth.role = r;
    render(<OptimizationCard />);
    expect(screen.getByRole("button", { name: /Run policy in simulator/ })).toBeEnabled();
    expect(screen.queryByText("Requires operator role")).toBeNull();
  });

  it("a viewer sees it disabled with the reason", () => {
    auth.role = "viewer";
    render(<OptimizationCard />);
    expect(screen.getByRole("button", { name: /Run policy in simulator/ })).toBeDisabled();
    expect(screen.getByText("Requires operator role")).toBeInTheDocument();
  });
});
