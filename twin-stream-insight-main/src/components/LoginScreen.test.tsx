import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const login = vi.fn();
let notice: string | null = null;
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ status: "signed-out", username: null, role: null, notice, login, logout: vi.fn() }),
}));

import { LoginScreen } from "./LoginScreen.tsx";
import { LoginError } from "@/authClient";

function fill(user: string, pass: string) {
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: user } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: pass } });
}

describe("LoginScreen", () => {
  beforeEach(() => {
    login.mockReset();
    notice = null;
  });

  it("has labelled username/password fields and no way to create an account", () => {
    render(<LoginScreen />);
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.queryByText(/register|create account|sign up/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it("submits the entered credentials", async () => {
    login.mockResolvedValue(undefined);
    render(<LoginScreen />);
    fill("alice", "hunter22");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(login).toHaveBeenCalledWith("alice", "hunter22"));
  });

  it("shows the server's message on failure, clears the password and re-enables the form", async () => {
    login.mockRejectedValue(new LoginError("Invalid username or password.", 401));
    render(<LoginScreen />);
    fill("alice", "wrong");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Username")).toHaveValue("alice");
  });

  it("shows a generic message for an unexpected error (never the raw exception)", async () => {
    login.mockRejectedValue(new Error("TypeError: secret internals"));
    render(<LoginScreen />);
    fill("alice", "pw");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Sign-in failed. Please try again.");
    expect(alert).not.toHaveTextContent("secret internals");
  });

  it("disables the button and ignores a second submit while signing in", async () => {
    let finish!: () => void;
    login.mockReturnValue(new Promise<void>((r) => (finish = r)));
    render(<LoginScreen />);
    fill("alice", "pw");
    const form = screen.getByRole("button", { name: "Sign in" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(login).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
    finish();
  });

  it("shows the notice left by a session that ended", () => {
    notice = "Your session has ended. Please sign in again.";
    render(<LoginScreen />);
    expect(screen.getByRole("alert")).toHaveTextContent(/session has ended/i);
  });

  describe("session notice and errors (FE-13)", () => {
    it("shows the session-ended notice as its own alert with text, separate from a form error", () => {
      notice = "Session ended — sign in again";
      render(<LoginScreen />);
      const banner = screen.getByTestId("session-notice");
      expect(banner).toHaveAttribute("role", "alert");
      expect(banner).toHaveTextContent("Session ended — sign in again");
      expect(banner.querySelector("svg")).not.toBeNull(); // icon shape as well as text
      expect(document.getElementById("login-error")).toBeNull();
    });

    it("no notice: no banner", () => {
      render(<LoginScreen />);
      expect(screen.queryByTestId("session-notice")).toBeNull();
    });

    it("a failed sign-in is a role=alert tied to both fields; the notice stays visible beside it", async () => {
      notice = "Session ended — sign in again";
      login.mockRejectedValue(new LoginError("Invalid username or password.", 401));
      render(<LoginScreen />);
      fill("alice", "wrong");
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      const err = await screen.findByText("Invalid username or password.");
      expect(err).toHaveAttribute("role", "alert");
      expect(err).toHaveAttribute("id", "login-error");
      expect(screen.getByLabelText("Username")).toHaveAttribute("aria-describedby", "login-error");
      expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByTestId("session-notice")).toBeTruthy();
    });

    it("has no registration or account-creation control", () => {
      render(<LoginScreen />);
      expect(screen.queryByRole("link", { name: /register|sign up|create/i })).toBeNull();
      expect(screen.queryByRole("button", { name: /register|sign up|create/i })).toBeNull();
    });
  });
});
