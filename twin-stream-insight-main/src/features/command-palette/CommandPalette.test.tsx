import "@/test/resizeObserver";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { createCommandRegistry } from "../commands";
import { createFeatureRegistry } from "../registry";
import { PaletteHost } from "./CommandPaletteHost";
import CommandPaletteWidget from "./CommandPaletteHost";
import { RECENTS_KEY } from "./recents";

let currentRole: string | null = "viewer";
vi.mock("@/hooks/useAuth.ts", () => ({ useRole: () => ({ role: currentRole }) }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

const scenarioState = vi.hoisted(() => ({ value: { status: "loading" } as unknown }));
const savedSelection = vi.hoisted(() => ({ ids: [] as string[] }));
vi.mock("@/scenarios", () => ({
  isScenarioLibraryEnabled: () => true,
  saveSelectedId: (id: string) => savedSelection.ids.push(id),
  useScenarios: () => ({ state: scenarioState.value }),
}));

beforeAll(() => {
  // cmdk scrolls the highlighted row into view; jsdom has no layout engine.
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  currentRole = "viewer";
  scenarioState.value = { status: "loading" };
  savedSelection.ids = [];
  window.localStorage.clear();
});

const Where = () => <span data-testid="where">{useLocation().pathname}</span>;
const features = createFeatureRegistry([], { onReject: () => undefined });

function setup(registry = createCommandRegistry(() => undefined)) {
  const utils = render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <button>outside</button>
        <CommandPaletteWidgetWithRegistries registry={registry} />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { registry, ...utils };
}

// The slot widget takes no props; tests inject registries through the host and give it the router's navigate.
function CommandPaletteWidgetWithRegistries({ registry }: { registry: ReturnType<typeof createCommandRegistry> }) {
  const navigate = useNavigate();
  return <PaletteHost navigate={(p) => navigate(p)} registry={registry} features={features} />;
}

const ctrlK = () => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
const palette = () => screen.queryByRole("dialog", { name: "Command palette" });
const input = () => screen.getByPlaceholderText("Type a command or search…");

describe("command palette: open, search, execute, close", () => {
  it("Ctrl+K opens it, Ctrl+K again closes it", async () => {
    setup();
    expect(palette()).toBeNull();
    ctrlK();
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    ctrlK();
    await waitFor(() => expect(palette()).toBeNull());
  });

  it("Cmd+K works too, and the trigger button opens it", async () => {
    setup();
    fireEvent.keyDown(document.body, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(palette()).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /Commands/ }));
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("search narrows the list; no match says so", async () => {
    setup();
    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    expect(screen.getByText("Go to Telemetry history")).toBeInTheDocument();
    fireEvent.change(input(), { target: { value: "analyt" } });
    await waitFor(() => expect(screen.queryByText("Go to Telemetry history")).toBeNull());
    expect(screen.getByText("Go to Analytics")).toBeInTheDocument();
    fireEvent.change(input(), { target: { value: "zzzzqqqq" } });
    expect(await screen.findByText("No matching commands.")).toBeInTheDocument();
  });

  it("choosing a page runs it, closes the palette and remembers it as recent", async () => {
    setup();
    ctrlK();
    fireEvent.click(await screen.findByText("Go to Analytics"));
    expect(screen.getByTestId("where")).toHaveTextContent("/analytics");
    await waitFor(() => expect(palette()).toBeNull());
    expect(JSON.parse(window.localStorage.getItem(RECENTS_KEY) ?? "[]")).toEqual(["page:/analytics"]);
    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    expect(screen.getByText("Recent")).toBeInTheDocument();
    // The first row of the Recent group is the one just used.
    expect(screen.getAllByText("Go to Analytics")).toHaveLength(2);
  });

  it("Enter runs the highlighted result (keyboard only)", async () => {
    setup();
    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    fireEvent.change(input(), { target: { value: "telemetry" } });
    await waitFor(() => expect(screen.queryByText("Go to Analytics")).toBeNull());
    fireEvent.keyDown(input(), { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/telemetry"));
    await waitFor(() => expect(palette()).toBeNull());
  });

  it("Escape closes it and focus goes back to where it was", async () => {
    setup();
    const outside = screen.getByRole("button", { name: "outside" });
    outside.focus();
    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    expect(outside).not.toHaveFocus();
    fireEvent.keyDown(input(), { key: "Escape" });
    await waitFor(() => expect(palette()).toBeNull());
    await waitFor(() => expect(outside).toHaveFocus());
  });

  it("ignores Ctrl+K while another dialog is already open", async () => {
    setup();
    const other = document.createElement("div");
    other.setAttribute("role", "dialog");
    document.body.appendChild(other);
    ctrlK();
    expect(palette()).toBeNull();
    other.remove();
  });

  it("a command that throws is contained", async () => {
    const registry = createCommandRegistry(() => undefined);
    registry.register("t", [{ id: "t.boom", label: "Boom", run: () => { throw new Error("x"); } }]);
    setup(registry);
    ctrlK();
    fireEvent.click(await screen.findByText("Boom"));
    await waitFor(() => expect(palette()).toBeNull());
  });
});

describe("registry-contributed commands", () => {
  it("shows a feature's command, runs it, and follows registration changes", async () => {
    const registry = createCommandRegistry(() => undefined);
    const run = vi.fn();
    const off = registry.register("demo", [{ id: "demo.hello", label: "Say hello", group: "Demo", keywords: ["greet"], shortcut: "G H", run }]);
    setup(registry);
    ctrlK();
    expect(await screen.findByText("Say hello")).toBeInTheDocument();
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(screen.getByText("G H")).toBeInTheDocument();
    fireEvent.change(input(), { target: { value: "greet" } }); // matched through keywords
    expect(await screen.findByText("Say hello")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Say hello"));
    expect(run).toHaveBeenCalledTimes(1);

    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    act(() => {
      registry.register("late", [{ id: "late.one", label: "Added later", run: () => undefined }]);
    });
    expect(await screen.findByText("Added later")).toBeInTheDocument();
    act(() => off());
    await waitFor(() => expect(screen.queryByText("Say hello")).toBeNull());
  });

  it("hides a command the role may not use", async () => {
    const registry = createCommandRegistry(() => undefined);
    registry.register("ops", [{ id: "ops.ack", label: "Acknowledge alert", minRole: "operator", run: () => undefined }]);
    setup(registry);
    ctrlK();
    await screen.findByRole("dialog", { name: "Command palette" });
    expect(screen.queryByText("Acknowledge alert")).toBeNull();
  });
});

describe("scenarios", () => {
  it("lists backend scenarios and selects the chosen one before opening analytics", async () => {
    scenarioState.value = { status: "ready", data: { registry_version: "1", scenarios: [{ id: "heatwave-1", label: "Heatwave week" }] } };
    setup();
    ctrlK();
    fireEvent.click(await screen.findByText("Scenario: Heatwave week"));
    expect(savedSelection.ids).toEqual(["heatwave-1"]);
    expect(screen.getByTestId("where")).toHaveTextContent("/analytics");
  });
});

describe("? shortcuts dialog", () => {
  it("opens on ?, lists the shortcuts, closes on Escape", async () => {
    setup();
    fireEvent.keyDown(document.body, { key: "?", shiftKey: true });
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
    expect(screen.getByText("Open or close the command palette")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull());
  });

  it("does not open while typing in a text field", async () => {
    setup();
    render(<input aria-label="notes" />);
    fireEvent.keyDown(screen.getByLabelText("notes"), { key: "?", shiftKey: true });
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("lists a feature's shortcut hint", async () => {
    const registry = createCommandRegistry(() => undefined);
    registry.register("demo", [{ id: "demo.go", label: "Go demo", shortcut: "G D", run: () => undefined }]);
    setup(registry);
    fireEvent.keyDown(document.body, { key: "?", shiftKey: true });
    await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(screen.getByText("G D")).toBeInTheDocument();
  });
});

describe("outside a router (existing tests render AccountMenu this way)", () => {
  it("the slot widget mounts, shows its button and opens without page rows", async () => {
    render(<CommandPaletteWidget />);
    expect(screen.getByRole("button", { name: /Commands/ })).toBeInTheDocument();
    ctrlK();
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(screen.queryByText("Go to Analytics")).toBeNull();
  });
});
