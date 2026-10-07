import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

type Status = "restoring" | "signed-out" | "signed-in";
let status: Status = "signed-out";
const logout = vi.fn();
const initAuth = vi.fn(() => Promise.resolve());

vi.mock("@/hooks/useAuth", async (orig) => ({
  ...(await orig<typeof import("@/hooks/useAuth.tsx")>()),
  useAuth: () => ({ status, username: "alice", role: "operator", notice: null, login: vi.fn(), logout }),
  useRole: () => ({ role: "operator", known: true, isOperator: true, operatorOnly: { disabled: false, reason: null } }),
}));
vi.mock("@/authClient", async (orig) => ({ ...(await orig<typeof import("@/authClient")>()), initAuth: () => initAuth() }));

import { AuthGate } from "./AuthGate.tsx";

const mounted = vi.fn();
function Protected() {
  mounted();
  return <div>protected content</div>;
}

function renderGate(client = new QueryClient()) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AuthGate>
          <Protected />
        </AuthGate>
      </QueryClientProvider>
    ),
  };
}

describe("AuthGate", () => {
  beforeEach(() => {
    mounted.mockClear();
    logout.mockClear();
    initAuth.mockClear();
  });

  it("shows the login screen and never mounts the app when signed out", () => {
    status = "signed-out";
    renderGate();
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(mounted).not.toHaveBeenCalled(); // so no API request, no WebSocket
  });

  it("shows a status message and not the app while restoring a session", () => {
    status = "restoring";
    renderGate();
    expect(screen.getByRole("status")).toHaveTextContent(/signing in/i);
    expect(mounted).not.toHaveBeenCalled();
  });

  it("renders the app and the account control when signed in; sign out calls logout", () => {
    status = "signed-in";
    renderGate();
    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Account" })).toHaveTextContent("alice");
    expect(screen.getByRole("group", { name: "Account" })).toHaveTextContent(/operator/i);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("starts auth initialisation once on mount", () => {
    status = "signed-out";
    renderGate();
    expect(initAuth).toHaveBeenCalledTimes(1);
  });

  it("drops the query cache when signed out so the next user never sees old data", () => {
    status = "signed-out";
    const client = new QueryClient();
    client.setQueryData(["alerts"], [{ id: 1 }]);
    renderGate(client);
    expect(client.getQueryData(["alerts"])).toBeUndefined();
  });
});
