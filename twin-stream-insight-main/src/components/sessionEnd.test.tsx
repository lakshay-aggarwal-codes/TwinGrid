/**
 * FE-13: the whole path with the REAL authClient/useAuth/AuthGate/LoginScreen (only `fetch` is faked):
 * a session that the server stops accepting lands on the sign-in screen with "Session ended — sign in again",
 * and nothing behind the gate is mounted any more.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

function fakeJwt(expSeconds: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSeconds }))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `h.${payload}.s`;
}
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = (status: number) => ({ ok: false, status, statusText: "x", json: async () => ({}) });
const tokens = (exp: number, refresh: string, role = "operator") => ({ access_token: fakeJwt(exp), refresh_token: refresh, token_type: "bearer", role });

const mounted = vi.fn();
function Protected() {
  mounted();
  return <div>protected content</div>;
}

async function setup(fetchMock: ReturnType<typeof vi.fn>) {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
  vi.stubGlobal("fetch", fetchMock);
  const { AuthGate } = await import("./AuthGate");
  const auth = await import("@/authClient");
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthGate>
        <Protected />
      </AuthGate>
    </QueryClientProvider>
  );
  return auth;
}

beforeEach(() => {
  sessionStorage.clear();
  mounted.mockClear();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("session ending (FE-13)", () => {
  it("refresh rejected by the server -> sign-in screen with the notice; the app is unmounted", async () => {
    const f = vi.fn().mockResolvedValueOnce(ok(tokens(5, "r1"))).mockResolvedValueOnce(fail(401));
    const auth = await setup(f);
    await screen.findByLabelText("Username"); // signed out first
    await act(async () => auth.login("alice", "pw"));
    expect(await screen.findByText("protected content")).toBeTruthy();
    expect(screen.getByTestId("account-role")).toHaveTextContent("Role: Operator");

    await act(async () => {
      await auth.getToken().catch(() => undefined); // close to expiry -> refresh -> 401
    });
    await waitFor(() => expect(screen.getByTestId("session-notice")).toHaveTextContent("Session ended — sign in again"));
    expect(screen.queryByText("protected content")).toBeNull();
    expect(screen.queryByTestId("account-role")).toBeNull();
  });

  it("endSession() (the server refused the session) routes to the same screen", async () => {
    const auth = await setup(vi.fn().mockResolvedValue(ok(tokens(900, "r1", "viewer"))));
    await screen.findByLabelText("Username");
    await act(async () => auth.login("alice", "pw"));
    await screen.findByText("protected content");
    expect(screen.getByTestId("account-role")).toHaveTextContent("Role: Viewer");

    act(() => auth.endSession());
    await waitFor(() => expect(screen.getByTestId("session-notice")).toHaveTextContent("Session ended — sign in again"));
    expect(screen.queryByText("protected content")).toBeNull();
  });

  it("signing out yourself shows no 'Session ended' notice", async () => {
    const auth = await setup(vi.fn().mockResolvedValue(ok(tokens(900, "r1"))));
    await screen.findByLabelText("Username");
    await act(async () => auth.login("alice", "pw"));
    await screen.findByText("protected content");
    await act(async () => auth.logout());
    await screen.findByLabelText("Username");
    expect(screen.queryByTestId("session-notice")).toBeNull();
  });

  it("the server cannot be reached on reload: the stored session is kept and the screen says why (not 'Session ended')", async () => {
    sessionStorage.setItem("twingrid.session", JSON.stringify({ refreshToken: "r-old", username: "alice" }));
    await setup(vi.fn().mockRejectedValue(new TypeError("network")));
    await waitFor(() => expect(screen.getByTestId("session-notice")).toHaveTextContent(/Could not reach the server/));
    expect(screen.getByTestId("session-notice")).not.toHaveTextContent("Session ended");
    expect(sessionStorage.getItem("twingrid.session")).toContain("r-old");
  });
});
