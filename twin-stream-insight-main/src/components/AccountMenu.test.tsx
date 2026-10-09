import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

let role: string | null = "viewer";
const logout = vi.fn();
vi.mock("@/hooks/useAuth.ts", async () => {
  const real = await vi.importActual<typeof import("@/hooks/useAuth.ts")>("@/hooks/useAuth");
  return {
    ...real,
    useAuth: () => ({ status: "signed-in", username: "alice", role, notice: null, login: vi.fn(), logout }),
    useRole: () => real.roleView(role),
  };
});

import { AccountMenu } from "./AccountMenu.tsx";

describe("AccountMenu", () => {
  it.each([
    ["viewer", "Role: Viewer", "true"],
    ["operator", "Role: Operator", "true"],
    ["auditor", "Role: unrecognised", "false"],
    [null, "Role: not reported", "false"],
  ])("shows the role as text (%j)", (r, text, known) => {
    role = r;
    render(<AccountMenu />);
    const el = screen.getByTestId("account-role");
    expect(el).toHaveTextContent(text);
    expect(el).toHaveAttribute("data-role-known", known);
    expect(screen.getByText("alice")).toBeTruthy();
  });

  it("an unrecognised role string is never echoed into the page", () => {
    role = "<img src=x onerror=alert(1)>";
    const { container } = render(<AccountMenu />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).not.toContain("onerror");
  });

  it("says in text that the role is a hint and the server decides", () => {
    role = "operator";
    render(<AccountMenu />);
    expect(screen.getByTestId("account-role")).toHaveAttribute("title", expect.stringMatching(/server decides/));
  });

  it("sign out is a keyboard-operable button", () => {
    role = "viewer";
    render(<AccountMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(logout).toHaveBeenCalled();
  });
});
