import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

type Snap = { status: "signed-in" | "signed-out"; username: string | null; role: string | null; notice: string | null };
let snap: Snap = { status: "signed-out", username: null, role: null, notice: null };
const listeners = new Set<() => void>();
const setSnap = (s: Snap) => {
  snap = s;
  listeners.forEach((l) => l());
};

vi.mock("@/authClient", () => ({
  getAuthSnapshot: () => snap,
  subscribeAuth: (l: () => void) => {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  login: vi.fn(),
  logout: vi.fn(),
}));

import { OPERATOR_REQUIRED_TEXT, roleView, useRole } from "./useAuth";

beforeEach(() => {
  listeners.clear();
  snap = { status: "signed-out", username: null, role: null, notice: null };
});

describe("roleView (UX gating, not authorisation)", () => {
  it("only the exact backend value 'operator' enables operator controls", () => {
    expect(roleView("operator")).toMatchObject({ known: true, isOperator: true, operatorOnly: { disabled: false, reason: null } });
  });

  it("a viewer is told in text why the control is disabled", () => {
    expect(roleView("viewer")).toMatchObject({
      known: true,
      isOperator: false,
      operatorOnly: { disabled: true, reason: "Requires operator role" },
    });
    expect(OPERATOR_REQUIRED_TEXT).toBe("Requires operator role");
  });

  it.each([["Operator"], ["OPERATOR"], ["admin"], ["operator "], [""]])("unrecognised or differently-cased role %j is not operator", (r) => {
    const v = roleView(r);
    expect(v.isOperator).toBe(false);
    expect(v.known).toBe(false);
    expect(v.operatorOnly.disabled).toBe(true);
    expect(v.role).toBe(r); // kept as stated, not rewritten
  });

  it("signed out (no role): not operator, role null, disabled with the same text", () => {
    expect(roleView(null)).toMatchObject({ role: null, known: false, isOperator: false, operatorOnly: { disabled: true, reason: OPERATOR_REQUIRED_TEXT } });
  });
});

describe("useRole", () => {
  it("follows the signed-in role and updates when the session changes", () => {
    const { result } = renderHook(() => useRole());
    expect(result.current.isOperator).toBe(false);
    act(() => setSnap({ status: "signed-in", username: "a", role: "operator", notice: null }));
    expect(result.current.isOperator).toBe(true);
    expect(result.current.operatorOnly.disabled).toBe(false);
    act(() => setSnap({ status: "signed-in", username: "a", role: "viewer", notice: null }));
    expect(result.current.isOperator).toBe(false);
    expect(result.current.operatorOnly.reason).toBe(OPERATOR_REQUIRED_TEXT);
    act(() => setSnap({ status: "signed-out", username: null, role: null, notice: "x" }));
    expect(result.current.role).toBeNull();
  });
});
