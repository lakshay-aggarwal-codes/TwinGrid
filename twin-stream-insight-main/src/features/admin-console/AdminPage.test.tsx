import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/apiError";
import type { DataState } from "@/state/dataState";
import { auditFixture, deliveriesFixture, systemFixture, testResult, usersFixture, webhooksFixture } from "./testFixtures";

// ---- mocks: the hooks (data) and the one direct API call (export); nothing touches the network
let role: string | null = "admin";
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ role }) }));
vi.mock("@/hooks/usePageTitle", () => ({ usePageTitle: () => undefined }));

const refetch = vi.fn();
const ready = <T,>(data: T): DataState<T> => ({ status: "ready", data });
let usersState: DataState<ReturnType<typeof usersFixture>>;
let auditState: DataState<ReturnType<typeof auditFixture>>;
let webhooksState: DataState<ReturnType<typeof webhooksFixture>>;
let deliveriesState: DataState<ReturnType<typeof deliveriesFixture>>;
let systemState: DataState<ReturnType<typeof systemFixture>>;
const setRole = vi.fn();
const hookActions = { create: vi.fn(), replace: vi.fn(), remove: vi.fn(), test: vi.fn() };
const useUsers = vi.fn(() => ({ state: usersState, refetch }));
const useAudit = vi.fn((_q: string, _enabled?: boolean) => ({ state: auditState, refetch }));
const useWebhooks = vi.fn(() => ({ state: webhooksState, refetch }));
const useDeliveries = vi.fn((_id: string | null) => ({ state: deliveriesState, refetch }));
const useSystem = vi.fn(() => ({ state: systemState, refetch }));
vi.mock("./useAdmin", () => ({
  useUsers: () => useUsers(),
  useAudit: (q: string, e?: boolean) => useAudit(q, e),
  useWebhooks: () => useWebhooks(),
  useDeliveries: (id: string | null) => useDeliveries(id),
  useSystem: () => useSystem(),
  useUserActions: () => ({ setRole }),
  useWebhookActions: () => hookActions,
}));
const downloadAudit = vi.fn();
vi.mock("./api", () => ({ downloadAudit: (...a: unknown[]) => downloadAudit(...a) }));

import AdminPage from "./AdminPage";
import { AuditPanel } from "./AuditPanel";
import { SystemPanel } from "./SystemPanel";
import { UsersPanel } from "./UsersPanel";
import { WebhooksPanel } from "./WebhooksPanel";

const lastAuditQuery = () => useAudit.mock.calls[useAudit.mock.calls.length - 1][0];
const lastAuditEnabled = () => useAudit.mock.calls[useAudit.mock.calls.length - 1][1];
const settle = () => act(async () => {});

beforeEach(() => {
  role = "admin";
  vi.clearAllMocks();
  usersState = ready(usersFixture());
  auditState = ready(auditFixture());
  webhooksState = ready(webhooksFixture());
  deliveriesState = ready(deliveriesFixture());
  systemState = ready(systemFixture());
});

describe("AdminPage gate (UX; the backend answers 403 regardless)", () => {
  it.each([null, "viewer", "operator", "root", "Admin"])("shows only 'Admin role required' for role %j and fetches nothing", (r) => {
    role = r;
    render(<AdminPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Admin console" })).toBeInTheDocument();
    expect(screen.getByTestId("admin-denied")).toHaveTextContent("Admin role required");
    expect(screen.queryByTestId("users-panel")).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
    for (const hook of [useUsers, useAudit, useWebhooks, useDeliveries, useSystem]) expect(hook).not.toHaveBeenCalled();
  });

  it("an admin sees the five tabs and the Users panel first, and nothing else is fetched yet", () => {
    render(<AdminPage />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Users", "Access requests", "Audit log", "Webhooks", "System"]);
    expect(screen.getByTestId("users-panel")).toBeInTheDocument();
    expect(useUsers).toHaveBeenCalled();
    for (const hook of [useAudit, useWebhooks, useSystem]) expect(hook).not.toHaveBeenCalled();
  });

  it("opening a tab mounts that panel (and fetches its data)", () => {
    render(<AdminPage />);
    fireEvent.mouseDown(screen.getByRole("tab", { name: "System" }), { button: 0, ctrlKey: false });
    expect(screen.getByTestId("system-panel")).toBeInTheDocument();
    expect(useSystem).toHaveBeenCalled();
  });
});

describe("UsersPanel", () => {
  it("lists users with role counts; you cannot change your own role; an unknown role is shown as unrecognised", () => {
    render(<UsersPanel />);
    expect(screen.getByTestId("user-counts")).toHaveTextContent("Viewer: 1 · Operator: 1 · Admin: 1");
    const me = screen.getByTestId("user-1");
    expect(within(me).getByText("You")).toBeInTheDocument();
    expect(within(me).getByText("You cannot change your own role.")).toBeInTheDocument();
    expect(within(me).queryByRole("combobox")).toBeNull();
    expect(screen.getByTestId("user-4-role")).toHaveTextContent("root (unrecognised)");
    expect(screen.getByRole("combobox", { name: "Role for alice" })).toHaveValue("viewer");
  });

  it("'Set role' is disabled until the choice differs, then sends exactly that and shows the server's answer", async () => {
    setRole.mockResolvedValue({ role: "operator" });
    render(<UsersPanel />);
    const apply = screen.getByTestId("user-2-apply");
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Role for alice" }), { target: { value: "operator" } });
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    await settle();
    expect(setRole).toHaveBeenCalledWith(2, "operator");
    expect(screen.getByTestId("user-2-done")).toHaveTextContent("Role set to Operator.");
  });

  it("a refused change shows kind-based wording (never the server's text) and puts the choice back", async () => {
    setRole.mockRejectedValue(new ApiError({ kind: "conflict", status: 409 }));
    render(<UsersPanel />);
    const select = screen.getByRole("combobox", { name: "Role for alice" });
    fireEvent.change(select, { target: { value: "admin" } });
    fireEvent.click(screen.getByTestId("user-2-apply"));
    await settle();
    expect(screen.getByTestId("user-2-error")).toHaveTextContent("That change is not possible right now");
    expect(select).toHaveValue("viewer");
    setRole.mockRejectedValue(new ApiError({ kind: "forbidden", status: 403 }));
    fireEvent.change(select, { target: { value: "admin" } });
    fireEvent.click(screen.getByTestId("user-2-apply"));
    await settle();
    expect(screen.getByTestId("user-2-error")).toHaveTextContent("Only admins can change this role.");
  });

  it("shows loading and error states instead of a table", () => {
    usersState = { status: "loading" };
    const { unmount } = render(<UsersPanel />);
    expect(screen.queryByRole("table")).toBeNull();
    unmount();
    usersState = { status: "error", kind: "rate_limited" };
    render(<UsersPanel />);
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("AuditPanel", () => {
  it("shows rows as plain text (a formula-looking name is just text) with outcome words", () => {
    render(<AuditPanel />);
    const row = screen.getByTestId("audit-9");
    expect(within(row).getByText("=cmd|x")).toBeInTheDocument();
    expect(row).toHaveTextContent("Failure");
    expect(row).toHaveTextContent("reason: bad password");
    expect(screen.getByTestId("audit-8")).toHaveTextContent("webhook abcd");
    expect(lastAuditQuery()).toBe("limit=50");
    expect(lastAuditEnabled()).toBe(true);
  });

  it("pages older and newer by cursor", () => {
    render(<AuditPanel />);
    expect(screen.getByTestId("audit-newer")).toBeDisabled();
    fireEvent.click(screen.getByTestId("audit-older"));
    expect(lastAuditQuery()).toBe("limit=50&before_id=8");
    expect(screen.getByTestId("audit-newer")).toBeEnabled();
    fireEvent.click(screen.getByTestId("audit-newer"));
    expect(lastAuditQuery()).toBe("limit=50");
  });

  it("applying filters builds the query and returns to the newest page; clearing resets", () => {
    render(<AuditPanel />);
    fireEvent.click(screen.getByTestId("audit-older"));
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "login_failure" } });
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "failure" } });
    fireEvent.change(screen.getByLabelText("User"), { target: { value: "mallory" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(lastAuditQuery()).toBe("action=login_failure&outcome=failure&username=mallory&limit=50");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(lastAuditQuery()).toBe("limit=50");
  });

  it("an invalid filter shows an alert and does not change the request", () => {
    render(<AuditPanel />);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-02-01T00:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-01-01T00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.getByTestId("audit-form-error")).toHaveTextContent("From is after To.");
    expect(lastAuditQuery()).toBe("limit=50");
  });

  it("export sends the APPLIED filters (no paging), saves the file and says how many rows", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    downloadAudit.mockResolvedValue({ blob: new Blob(["a"]), filename: "audit-log-20260101T120000Z.csv", rows: 2, truncated: false });
    render(<AuditPanel />);
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "login_failure" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    fireEvent.click(screen.getByTestId("export-csv"));
    await settle();
    expect(downloadAudit).toHaveBeenCalledWith("action=login_failure", "csv");
    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(screen.getByTestId("export-message")).toHaveTextContent("Exported 2 rows as audit-log-20260101T120000Z.csv.");
    click.mockRestore();
  });

  it("says when an export was cut off, and words a failed export by kind", async () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    downloadAudit.mockResolvedValueOnce({ blob: new Blob(["a"]), filename: "x.json", rows: 10000, truncated: true });
    render(<AuditPanel />);
    fireEvent.click(screen.getByTestId("export-json"));
    await settle();
    expect(screen.getByTestId("export-message")).toHaveTextContent("Only the newest 10,000 matching rows are included.");
    downloadAudit.mockRejectedValueOnce(new ApiError({ kind: "forbidden", status: 403 }));
    fireEvent.click(screen.getByTestId("export-csv"));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Only admins can export the audit log.");
    click.mockRestore();
  });

  it("shows the empty and error states instead of a table", () => {
    auditState = { status: "empty" };
    const { unmount } = render(<AuditPanel />);
    expect(screen.queryByTestId("audit-table")).toBeNull();
    unmount();
    auditState = { status: "error", kind: "server" };
    render(<AuditPanel />);
    expect(screen.queryByTestId("audit-table")).toBeNull();
  });
});

describe("WebhooksPanel", () => {
  const id = "0123456789abcdef";

  it("names webhooks by scheme, host and port only, with their last delivery in words", () => {
    render(<WebhooksPanel />);
    expect(screen.getByTestId(`webhook-${id}-label`)).toHaveTextContent("https://hooks.example.com");
    expect(screen.getByTestId("webhook-fedcba9876543210-label")).toHaveTextContent("https://other.example.com:8443");
    expect(screen.getAllByText(/path and query hidden/).length).toBe(2);
    expect(screen.getByTestId(`webhook-${id}-last`)).toHaveTextContent("Last delivery (Test, 2026-01-01 12:00:00 UTC): Delivered (HTTP 200) in 42 ms");
    expect(screen.getByTestId("webhook-fedcba9876543210-last")).toHaveTextContent("No delivery recorded yet.");
    expect(screen.getByTestId("webhook-simulated-note")).toHaveTextContent("do not fire webhooks");
    expect(screen.getByTestId("webhook-simulated-note")).toHaveTextContent("2 of 20 subscribers in use.");
  });

  it("test-fire shows the result in words, for a delivery and for a failure", async () => {
    hookActions.test.mockResolvedValueOnce(testResult());
    render(<WebhooksPanel />);
    fireEvent.click(screen.getByTestId(`webhook-${id}-test`));
    await settle();
    expect(hookActions.test).toHaveBeenCalledWith(id);
    expect(screen.getByTestId(`webhook-${id}-result`)).toHaveTextContent("Test event: Delivered (HTTP 200) in 12 ms.");
    hookActions.test.mockResolvedValueOnce(testResult({ ok: false, status_code: 500, error_kind: "http_error" }));
    fireEvent.click(screen.getByTestId(`webhook-${id}-test`));
    await settle();
    expect(screen.getByTestId(`webhook-${id}-result`)).toHaveTextContent("Failed: the endpoint returned an error (HTTP 500)");
  });

  it("changing a URL needs a value, sends it, and then never shows it", async () => {
    hookActions.replace.mockResolvedValue(webhooksFixture());
    render(<WebhooksPanel />);
    fireEvent.click(screen.getByTestId(`webhook-${id}-edit`));
    fireEvent.click(screen.getByTestId(`webhook-${id}-save`));
    expect(screen.getByTestId(`webhook-${id}-error`)).toHaveTextContent("Enter a webhook URL.");
    expect(hookActions.replace).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId(`webhook-${id}-url`), { target: { value: "https://new.example.com/SECRETPATH?t=SECRETQ" } });
    fireEvent.click(screen.getByTestId(`webhook-${id}-save`));
    await settle();
    expect(hookActions.replace).toHaveBeenCalledWith(id, "https://new.example.com/SECRETPATH?t=SECRETQ");
    expect(screen.queryByTestId(`webhook-${id}-url`)).toBeNull();
    expect(screen.getByTestId(`webhook-${id}-saved`)).toHaveTextContent("It is not shown again.");
    expect(document.body.textContent).not.toContain("SECRETPATH");
    expect(document.body.textContent).not.toContain("SECRETQ");
  });

  it("a rejected URL is worded by kind, never with the server's text", async () => {
    hookActions.replace.mockRejectedValue(new ApiError({ kind: "validation", status: 422 }));
    render(<WebhooksPanel />);
    fireEvent.click(screen.getByTestId(`webhook-${id}-edit`));
    fireEvent.change(screen.getByTestId(`webhook-${id}-url`), { target: { value: "http://x.example.com" } });
    fireEvent.click(screen.getByTestId(`webhook-${id}-save`));
    await settle();
    expect(screen.getByTestId(`webhook-${id}-error`)).toHaveTextContent("Webhook URLs must be https and public.");
  });

  it("removing needs a second, explicit confirmation", async () => {
    hookActions.remove.mockResolvedValue(webhooksFixture());
    render(<WebhooksPanel />);
    fireEvent.click(screen.getByTestId(`webhook-${id}-remove`));
    expect(hookActions.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.getByTestId(`webhook-${id}-remove`)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId(`webhook-${id}-remove`));
    fireEvent.click(screen.getByTestId(`webhook-${id}-confirm`));
    await settle();
    expect(hookActions.remove).toHaveBeenCalledWith(id);
  });

  it("adds a webhook (an empty entry is refused locally) and does not echo the URL", async () => {
    hookActions.create.mockResolvedValue(webhooksFixture());
    render(<WebhooksPanel />);
    fireEvent.click(screen.getByTestId("webhook-add-submit"));
    expect(screen.getByTestId("webhook-add-error")).toHaveTextContent("Enter a webhook URL.");
    expect(hookActions.create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("webhook-add-url"), { target: { value: "https://hooks.example.com/ADDSECRET" } });
    fireEvent.click(screen.getByTestId("webhook-add-submit"));
    await settle();
    expect(hookActions.create).toHaveBeenCalledWith("https://hooks.example.com/ADDSECRET");
    expect(screen.getByTestId("webhook-added")).toBeInTheDocument();
    expect((screen.getByTestId("webhook-add-url") as HTMLInputElement).value).toBe("");
    expect(document.body.textContent).not.toContain("ADDSECRET");
  });

  it("shows the delivery log in words and can filter it to one webhook", () => {
    render(<WebhooksPanel />);
    const rows = screen.getAllByTestId("delivery-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Test");
    expect(rows[0]).toHaveTextContent("Delivered (HTTP 200) in 42 ms");
    expect(rows[1]).toHaveTextContent("Alert");
    expect(rows[1]).toHaveTextContent("Failed: the endpoint returned an error (HTTP 500)");
    expect(screen.getByText(/With several API workers it is partial/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Webhook"), { target: { value: id } });
    expect(useDeliveries).toHaveBeenLastCalledWith(id);
  });

  it("says plainly when simulated alerts do fire webhooks", () => {
    webhooksState = ready(webhooksFixture({ fires_for_simulated_alerts: true }));
    render(<WebhooksPanel />);
    expect(screen.getByTestId("webhook-simulated-note")).toHaveTextContent("Alerts from simulated data do fire webhooks");
  });

  it("shows the empty state when none are registered", () => {
    webhooksState = { status: "empty" };
    render(<WebhooksPanel />);
    expect(screen.queryByRole("list", { name: "Registered webhooks" })).toBeNull();
    expect(screen.getByTestId("webhook-add")).toBeInTheDocument();
  });
});

describe("SystemPanel", () => {
  it("shows readiness, migration, versions, uptime, models and the docs links, each state as glyph plus word", () => {
    render(<SystemPanel />);
    expect(screen.getByTestId("system-ready-status")).toHaveTextContent("Ready");
    expect(screen.getByTestId("check-database")).toHaveTextContent("OK");
    expect(screen.getByTestId("component-optimizer")).toHaveTextContent("Loaded");
    expect(screen.getByTestId("component-anomaly_detector")).toHaveTextContent("Degraded");
    expect(screen.getByTestId("component-anomaly_detector").querySelector('[data-healthy="false"]')).not.toBeNull();
    expect(screen.getByTestId("system-migration")).toHaveTextContent("At head");
    expect(screen.getByTestId("system-migration")).toHaveTextContent("20261008000000");
    expect(screen.getByTestId("system-versions")).toHaveTextContent("Digital Twin API 1.0.0");
    expect(screen.getByTestId("system-versions")).toHaveTextContent("Safety envelope");
    expect(screen.getByTestId("system-uptime")).toHaveTextContent("2 h 5 min");
    expect(screen.getByTestId("system-uptime")).toHaveTextContent("since this process loaded the API plugins");
    expect(screen.getByTestId("system-models")).toHaveTextContent("promoted");
    for (const [name, href] of [["Swagger UI", "/docs"], ["ReDoc", "/redoc"], ["OpenAPI JSON", "/openapi.json"]] as const) {
      const link = screen.getByRole("link", { name: new RegExp(name) });
      expect(link.getAttribute("href")).toContain(href);
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(link).toHaveAttribute("target", "_blank");
    }
    expect(screen.queryByTestId("system-unavailable")).toBeNull();
  });

  it("a failing check is 'Not ready' and worded, not just coloured", () => {
    const s = systemFixture();
    systemState = ready({ ...s, readiness: { ...s.readiness!, status: "not_ready", checks: { database: "ok", schema: "behind", broadcast: "stale" } }, migration: { head: "b", database: "a", at_head: false } });
    render(<SystemPanel />);
    expect(screen.getByTestId("system-ready-status")).toHaveTextContent("Not ready");
    expect(screen.getByTestId("check-schema")).toHaveTextContent("Behind");
    expect(screen.getByTestId("check-broadcast")).toHaveTextContent("Stale");
    expect(screen.getByTestId("check-schema").querySelector('[data-healthy="false"]')).not.toBeNull();
    expect(screen.getByTestId("system-migration")).toHaveTextContent("Not at head");
  });

  it("parts the server could not read are NOT MEASURED, never blank or assumed fine", () => {
    systemState = ready(systemFixture({ readiness: null, migration: null, models: { state: null, registry: null }, unavailable: ["readiness", "migration", "model_registry"] }));
    render(<SystemPanel />);
    expect(screen.getByTestId("system-unavailable")).toHaveTextContent("readiness, migration, model_registry");
    expect(screen.getByTestId("system-readiness")).toHaveTextContent("NOT MEASURED: readiness could not be read.");
    expect(screen.getByTestId("system-migration")).toHaveTextContent("NOT MEASURED: the migration state could not be read.");
    expect(screen.getByTestId("system-models")).toHaveTextContent("NOT MEASURED: the model registry could not be read.");
    expect(screen.queryByText("Ready")).toBeNull();
  });

  it("an empty registry says so", () => {
    const s = systemFixture();
    systemState = ready({ ...s, models: { state: s.models.state, registry: [] } });
    render(<SystemPanel />);
    expect(screen.getByTestId("system-models")).toHaveTextContent("The model registry has no entries.");
  });

  it("shows loading and error states", () => {
    systemState = { status: "loading" };
    const { unmount } = render(<SystemPanel />);
    expect(screen.queryByTestId("system-readiness")).toBeNull();
    unmount();
    systemState = { status: "error", kind: "unavailable" };
    render(<SystemPanel />);
    expect(screen.queryByTestId("system-readiness")).toBeNull();
  });
});
