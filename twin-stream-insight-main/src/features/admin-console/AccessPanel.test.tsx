import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";
import type { DataState } from "@/state/dataState";
import { accessPage, accessRequest } from "./accessFixtures";
import type { AccessRequest, AccessRequests } from "./schema";

// ---- mocks: auth, the access hooks (data and actions) and the other panels' hooks; nothing touches the network
let role: string | null = "admin";
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role }) }));
vi.mock("@/hooks/usePageTitle", () => ({ usePageTitle: () => undefined }));

const refetch = vi.fn();
const loading = { status: "loading" } as DataState<never>;
const ready = <T,>(data: T): DataState<T> => ({ status: "ready", data });
let lists: Record<string, DataState<AccessRequests>> = {};
let detail: DataState<AccessRequest> = loading;
const useAccessRequests = vi.fn((q: string) => ({ state: lists[q] ?? (loading as DataState<AccessRequests>), refetch }));
const useAccessRequest = vi.fn((_id: string, _enabled: boolean) => ({ state: detail, refetch }));
const actions = { decide: vi.fn(), resendNotification: vi.fn(), resendActivation: vi.fn() };
vi.mock("./useAccessRequests", () => ({
  useAccessRequests: (q: string) => useAccessRequests(q),
  useAccessRequest: (id: string, e: boolean) => useAccessRequest(id, e),
  useAccessActions: () => actions,
}));
vi.mock("./useAdmin", () => ({
  useUsers: () => ({ state: loading, refetch }),
  useAudit: () => ({ state: loading, refetch }),
  useWebhooks: () => ({ state: loading, refetch }),
  useDeliveries: () => ({ state: loading, refetch }),
  useSystem: () => ({ state: loading, refetch }),
  useUserActions: () => ({ setRole: vi.fn() }),
  useWebhookActions: () => ({ create: vi.fn(), replace: vi.fn(), remove: vi.fn(), test: vi.fn() }),
}));

import { AccessPanel } from "./AccessPanel";
import AdminPage from "./AdminPage";
import { ACCESS_PAGE_SIZE, accessQuery, accessStatusLabel, canDecide, canResendActivation, canResendNotification, expiresText, notifyLabel, parseNote, utcText } from "./model";
import { AccessRequestSchema, AccessRequestsSchema } from "./schema";

const PENDING = accessQuery("pending");
const A = accessRequest();
const settle = () => act(async () => {});
const open = (decision: "approve" | "reject", item = A) => {
  const btn = screen.getByTestId(`access-${item.id}-${decision}`);
  btn.focus();
  fireEvent.click(btn);
  return btn;
};

beforeEach(() => {
  role = "admin";
  vi.clearAllMocks();
  lists = { [PENDING]: ready(accessPage([A])) };
  detail = loading;
  actions.decide.mockResolvedValue(accessRequest({ status: "approved" }));
  actions.resendNotification.mockResolvedValue(undefined);
  actions.resendActivation.mockResolvedValue(undefined);
});

describe("visibility: admin only", () => {
  it.each([null, "viewer", "operator", "root", "Admin"])("role %j gets no tab, no panel and no request", (r) => {
    role = r;
    render(<AdminPage />);
    expect(screen.queryByRole("tab", { name: "Access requests" })).toBeNull();
    expect(screen.queryByTestId("access-panel")).toBeNull();
    expect(useAccessRequests).not.toHaveBeenCalled();
  });

  it("an admin sees the tab, and nothing is fetched until it is opened", () => {
    render(<AdminPage />);
    expect(screen.getByRole("tab", { name: "Access requests" })).toBeInTheDocument();
    expect(useAccessRequests).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Access requests" }), { button: 0, ctrlKey: false });
    expect(screen.getByTestId("access-panel")).toBeInTheDocument();
    expect(useAccessRequests).toHaveBeenCalledWith(PENDING);
  });
});

describe("states", () => {
  it("loading", () => {
    lists = {};
    render(<AccessPanel />);
    expect(screen.getByText("Loading access requests…")).toBeInTheDocument();
  });
  it("empty (pending) and empty (other filter)", () => {
    lists = { [PENDING]: { status: "empty" }, [accessQuery("rejected")]: { status: "empty" } };
    render(<AccessPanel />);
    expect(screen.getByText("No pending requests.")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("access-filter"), { target: { value: "rejected" } });
    expect(screen.getByText("No rejected requests.")).toBeInTheDocument();
  });
  it("error offers a retry that refetches", () => {
    lists = { [PENDING]: { status: "error", kind: "network" } };
    render(<AccessPanel />);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalled();
  });
  it("forbidden shows no retry loop and no list", () => {
    lists = { [PENDING]: { status: "unauthorized", reason: "forbidden" } };
    render(<AccessPanel />);
    expect(screen.queryByTestId("access-list")).toBeNull();
  });
});

describe("the list", () => {
  it("shows the submitted details, expiry and email status, as text", () => {
    lists = { [PENDING]: ready(accessPage([accessRequest({ name: "<b>Mallory</b>", purpose: "<img src=x onerror=1>", notify_state: "failed", notify_attempts: 2 })])) };
    const { container } = render(<AccessPanel />);
    const card = screen.getByTestId(`access-${A.id}`);
    expect(within(card).getByRole("heading", { level: 3 }).textContent).toBe("<b>Mallory</b>");
    expect(card).toHaveTextContent("ada@example.com");
    expect(card).toHaveTextContent("K7Q2M9XD4TAB");
    expect(card).toHaveTextContent("<img src=x onerror=1>");
    expect(container.querySelector("b, img")).toBeNull();
    expect(screen.getByTestId(`access-${A.id}-status`)).toHaveTextContent("Pending");
    expect(screen.getByTestId(`access-${A.id}-notify`)).toHaveTextContent("Email failed (2 attempts)");
    expect(screen.getByTestId(`access-${A.id}-expires`)).toHaveTextContent("2026-10-27 09:00 UTC");
  });

  it("never shows a token or hash, even if the server leaks one (the schema drops it)", () => {
    const leaky = { ...A, status_token_hash: "STATUSHASH", activation_token_hash: "ACTIVATIONHASH", activation_token: "RAWTOKEN" };
    lists = { [PENDING]: ready(AccessRequestsSchema.parse({ items: [leaky], next_before_id: null })) };
    const { container } = render(<AccessPanel />);
    for (const secret of ["STATUSHASH", "ACTIVATIONHASH", "RAWTOKEN"]) expect(container.textContent).not.toContain(secret);
  });

  it("the filter changes the query (and 'All' omits the status)", () => {
    render(<AccessPanel />);
    fireEvent.change(screen.getByTestId("access-filter"), { target: { value: "approved" } });
    expect(useAccessRequests).toHaveBeenLastCalledWith(`status=approved&limit=${ACCESS_PAGE_SIZE}`);
    fireEvent.change(screen.getByTestId("access-filter"), { target: { value: "all" } });
    expect(useAccessRequests).toHaveBeenLastCalledWith(`limit=${ACCESS_PAGE_SIZE}`);
  });

  it("pages with before_id: 'Load more' mounts the next page below and then goes away", () => {
    const B = accessRequest({ id: "id-b", ref: "BBBBBBBBBBBB", name: "Grace Hopper" });
    lists = { [PENDING]: ready(accessPage([A], "cursor-1")), [accessQuery("pending", "cursor-1")]: ready(accessPage([B], null)) };
    render(<AccessPanel />);
    expect(screen.queryByTestId("access-id-b")).toBeNull();
    fireEvent.click(screen.getByTestId("access-more"));
    expect(useAccessRequests).toHaveBeenCalledWith(`status=pending&limit=${ACCESS_PAGE_SIZE}&before_id=cursor-1`);
    expect(screen.getByTestId("access-id-b")).toBeInTheDocument();
    expect(screen.queryByTestId("access-more")).toBeNull();
  });

  it("details fetch the decision note only when opened", () => {
    detail = ready(accessRequest({ status: "rejected", decision_note: "Not a real person" }));
    render(<AccessPanel />);
    expect(useAccessRequest).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId(`access-${A.id}-toggle`));
    expect(useAccessRequest).toHaveBeenCalledWith(A.id, true);
    expect(screen.getByTestId(`access-${A.id}-note`)).toHaveTextContent("Not a real person");
    expect(screen.getByTestId(`access-${A.id}-toggle`)).toHaveAttribute("aria-expanded", "true");
  });
});

describe("which actions each status offers", () => {
  const cases: [string, Partial<AccessRequest>, string[]][] = [
    ["pending, email sent", { status: "pending", notify_state: "sent" }, ["approve", "reject"]],
    ["pending, email failed", { status: "pending", notify_state: "failed" }, ["approve", "reject", "resend-notification"]],
    ["pending, not configured", { status: "pending", notify_state: "not_configured" }, ["approve", "reject", "resend-notification"]],
    ["approved", { status: "approved" }, ["resend-activation"]],
    ["activated", { status: "activated" }, []],
    ["rejected", { status: "rejected" }, []],
    ["expired", { status: "expired" }, []],
    ["an unrecognised status", { status: "mystery" }, []],
  ];
  it.each(cases)("%s", (_n, over, expected) => {
    lists = { [PENDING]: ready(accessPage([accessRequest(over)])) };
    render(<AccessPanel />);
    const all = ["approve", "reject", "resend-notification", "resend-activation"];
    for (const a of all) {
      const el = screen.queryByTestId(`access-${A.id}-${a}`);
      if (expected.includes(a)) expect(el).not.toBeNull();
      else expect(el).toBeNull();
    }
  });
});

describe("approve and reject", () => {
  it("opens a confirmation first: nothing is sent, focus moves into the dialog, which has an accessible name", () => {
    render(<AccessPanel />);
    open("approve");
    const dialog = screen.getByRole("alertdialog", { name: "Approve this request?" });
    expect(dialog).toHaveTextContent("Ada Lovelace (ada@example.com, reference K7Q2M9XD4TAB)");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(actions.decide).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/Note \(optional/)).toBeInTheDocument();
  });

  it("confirming approve sends the note, closes the dialog, says so, and returns focus", async () => {
    render(<AccessPanel />);
    const trigger = open("approve");
    fireEvent.change(screen.getByLabelText(/Note \(optional/), { target: { value: "  Looks genuine  " } });
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    expect(actions.decide).toHaveBeenCalledExactlyOnceWith(A.id, "approve", "Looks genuine");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByTestId("access-notice")).toHaveTextContent("Approved K7Q2M9XD4TAB");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("reject without a note sends null", async () => {
    render(<AccessPanel />);
    open("reject");
    expect(screen.getByRole("alertdialog", { name: "Reject this request?" })).toHaveTextContent("No account is created.");
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    expect(actions.decide).toHaveBeenCalledExactlyOnceWith(A.id, "reject", null);
    expect(screen.getByTestId("access-notice")).toHaveTextContent("Rejected K7Q2M9XD4TAB");
  });

  it("when the decided row leaves the list, focus goes to the notices region instead of the page body", async () => {
    render(<AccessPanel />);
    open("approve");
    lists = { [PENDING]: { status: "empty" } };
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    await waitFor(() => expect(screen.getByTestId("access-notices")).toHaveFocus());
  });

  it("Cancel sends nothing and returns focus to the button that opened the dialog", async () => {
    render(<AccessPanel />);
    const trigger = open("reject");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settle();
    expect(actions.decide).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("Escape closes the dialog when idle", async () => {
    render(<AccessPanel />);
    open("approve");
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    await settle();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("while the request is in flight: one call only, controls locked, Escape and Cancel cannot dismiss it", async () => {
    let finish: (r: AccessRequest) => void = () => undefined;
    actions.decide.mockReturnValue(new Promise<AccessRequest>((r) => (finish = r)));
    render(<AccessPanel />);
    open("approve");
    const confirm = screen.getByTestId("access-confirm");
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await settle();
    expect(actions.decide).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveTextContent("Working…");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText(/Note \(optional/)).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    await settle();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await act(async () => finish(accessRequest({ status: "approved" })));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a 409 (already decided elsewhere) is explained, keeps the dialog open, and unlocks it", async () => {
    actions.decide.mockRejectedValue(new ApiError({ kind: "conflict", status: 409 }));
    render(<AccessPanel />);
    open("approve");
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    expect(screen.getByTestId("access-dialog-error")).toHaveTextContent("already decided");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByTestId("access-confirm")).toBeEnabled();
    expect(screen.getByTestId("access-notices")).not.toHaveTextContent("Approved");
  });

  it.each([
    [new ApiError({ kind: "not_found", status: 404 }), "no longer exists"],
    [new ApiError({ kind: "forbidden", status: 403 }), "Only admins"],
    [new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 30 }), "30 seconds"],
    [new ApiError({ kind: "validation", status: 422 }), "Shorten the note"],
    [new ApiError({ kind: "network" }), "Could not approve this request"],
  ])("other failures use fixed wording (%#)", async (err, text) => {
    actions.decide.mockRejectedValue(err);
    render(<AccessPanel />);
    open("approve");
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    expect(screen.getByTestId("access-dialog-error")).toHaveTextContent(text);
  });

  it("a note over the limit is refused client-side, not truncated", async () => {
    render(<AccessPanel />);
    open("approve");
    fireEvent.change(screen.getByLabelText(/Note \(optional/), { target: { value: "x".repeat(501) } });
    fireEvent.click(screen.getByTestId("access-confirm"));
    await settle();
    expect(actions.decide).not.toHaveBeenCalled();
    expect(screen.getByTestId("access-dialog-error")).toHaveTextContent("longer than 500");
    expect(screen.getByLabelText(/Note \(optional/)).toHaveAttribute("maxlength", "500");
  });
});

describe("resend", () => {
  it("resend notification calls the API for that request and says so", async () => {
    lists = { [PENDING]: ready(accessPage([accessRequest({ notify_state: "failed" })])) };
    render(<AccessPanel />);
    fireEvent.click(screen.getByTestId(`access-${A.id}-resend-notification`));
    await settle();
    expect(actions.resendNotification).toHaveBeenCalledExactlyOnceWith(A.id);
    expect(screen.getByTestId("access-notice")).toHaveTextContent("Notification email queued for K7Q2M9XD4TAB");
  });

  it("resend activation (approved only) works and locks the other buttons while in flight", async () => {
    let finish: () => void = () => undefined;
    actions.resendActivation.mockReturnValue(new Promise<void>((r) => (finish = r)));
    lists = { [PENDING]: ready(accessPage([accessRequest({ status: "approved" })])) };
    render(<AccessPanel />);
    const btn = screen.getByTestId(`access-${A.id}-resend-activation`);
    fireEvent.click(btn);
    fireEvent.click(btn);
    await settle();
    expect(actions.resendActivation).toHaveBeenCalledTimes(1);
    expect(btn).toBeDisabled();
    await act(async () => finish());
    expect(screen.getByTestId("access-notice")).toHaveTextContent("A new activation link is being sent");
    expect(btn).toBeEnabled();
  });

  it("a failed resend shows an alert and no success message", async () => {
    actions.resendActivation.mockRejectedValue(new ApiError({ kind: "conflict", status: 409 }));
    lists = { [PENDING]: ready(accessPage([accessRequest({ status: "approved" })])) };
    render(<AccessPanel />);
    fireEvent.click(screen.getByTestId(`access-${A.id}-resend-activation`));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("already decided or is no longer pending");
    expect(screen.queryByTestId("access-notice")).toBeNull();
  });
});

describe("keyboard and 375 px layout", () => {
  it("every control is a native button, select or textarea with a name (reachable by Tab, activated by Enter or Space)", () => {
    lists = { [PENDING]: ready(accessPage([accessRequest({ notify_state: "failed" })])) };
    const { container } = render(<AccessPanel />);
    expect(container.querySelectorAll("[role=button], a, [onclick]")).toHaveLength(0);
    for (const b of screen.getAllByRole("button")) {
      expect(b.tagName).toBe("BUTTON");
      expect(b).toHaveAccessibleName();
    }
    expect(screen.getByLabelText("Show")).toBeInTheDocument();
  });

  it("uses single-column cards (no table) with 44 px touch targets and wrapping text", () => {
    lists = { [PENDING]: ready(accessPage([accessRequest({ notify_state: "failed" })], "next")) };
    const { container } = render(<AccessPanel />);
    expect(container.querySelector("table")).toBeNull();
    expect(screen.getByTestId("access-list").className).toContain("grid-cols-1");
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    for (const b of buttons) expect(b.className).toMatch(/min-h-11[\s\S]*min-w-11|min-w-11[\s\S]*min-h-11/);
    expect(screen.getByTestId("access-filter").className).toContain("min-h-11");
    expect(screen.getByRole("heading", { level: 3 }).className).toContain("break-words");
    expect(container.querySelector("dd.break-all")).not.toBeNull();
  });
});

describe("model helpers", () => {
  it("accessQuery", () => {
    expect(accessQuery("pending")).toBe("status=pending&limit=20");
    expect(accessQuery("all", "abc")).toBe("limit=20&before_id=abc");
    expect(accessQuery("expired", 7)).toBe("status=expired&limit=20&before_id=7");
  });
  it("action predicates", () => {
    expect(canDecide({ status: "pending" })).toBe(true);
    expect(canDecide({ status: "approved" })).toBe(false);
    expect(canResendNotification({ status: "pending", notify_state: "sent" })).toBe(false);
    expect(canResendNotification({ status: "pending", notify_state: "failed" })).toBe(true);
    expect(canResendNotification({ status: "approved", notify_state: "failed" })).toBe(false);
    expect(canResendActivation({ status: "approved" })).toBe(true);
    expect(canResendActivation({ status: "pending" })).toBe(false);
  });
  it("parseNote trims, nulls a blank, refuses (never cuts) an over-long note", () => {
    expect(parseNote("  hi ")).toEqual({ ok: true, value: "hi" });
    expect(parseNote("   ")).toEqual({ ok: true, value: null });
    expect(parseNote("x".repeat(500))).toMatchObject({ ok: true });
    expect(parseNote("x".repeat(501))).toMatchObject({ ok: false });
  });
  it("time text handles Z and +00:00 and passes junk through", () => {
    expect(utcText("2026-10-27T09:00:00Z")).toBe("2026-10-27 09:00 UTC");
    expect(utcText("2026-10-27T09:00:00+00:00")).toBe("2026-10-27 09:00 UTC");
    expect(utcText(null)).toBe("unknown");
    expect(utcText("not a date")).toBe("not a date");
  });
  it("expiresText", () => {
    const now = Date.parse("2026-10-20T09:00:00Z");
    expect(expiresText("2026-10-27T09:00:00Z", now)).toBe("2026-10-27 09:00 UTC (in 7 days)");
    expect(expiresText("2026-10-20T20:00:00Z", now)).toBe("2026-10-20 20:00 UTC (in 11 h)");
    expect(expiresText("2026-10-20T09:20:00Z", now)).toBe("2026-10-20 09:20 UTC (in 20 min)");
    expect(expiresText("2026-10-19T09:00:00Z", now)).toBe("2026-10-19 09:00 UTC (expired)");
  });
  it("labels: unknown values are flagged, never hidden", () => {
    expect(accessStatusLabel("pending")).toBe("Pending");
    expect(accessStatusLabel("zzz")).toBe("zzz (unrecognised)");
    expect(notifyLabel("not_configured")).toBe("Email not configured");
    expect(notifyLabel("zzz")).toContain("unrecognised");
  });
});

describe("schema", () => {
  it("accepts the section 8.1 shape and drops unknown keys", () => {
    const parsed = AccessRequestSchema.parse({ ...A, extra: "x" });
    expect(parsed).toEqual(A);
    expect("extra" in parsed).toBe(false);
  });
  it("accepts a decision note, and a numeric or null cursor", () => {
    expect(AccessRequestSchema.parse({ ...A, decision_note: "n" }).decision_note).toBe("n");
    expect(AccessRequestsSchema.parse({ items: [], next_before_id: 7 }).next_before_id).toBe(7);
    expect(AccessRequestsSchema.parse({ items: [], next_before_id: null }).next_before_id).toBeNull();
  });
  it.each(["id", "ref", "name", "email", "status", "notify_state", "notify_attempts"])("rejects a response missing %s (never repaired)", (key) => {
    const bad: Record<string, unknown> = { ...A };
    delete bad[key];
    expect(AccessRequestSchema.safeParse(bad).success).toBe(false);
  });
  it("rejects a mistyped field", () => {
    expect(AccessRequestSchema.safeParse({ ...A, notify_attempts: "1" }).success).toBe(false);
  });
});
