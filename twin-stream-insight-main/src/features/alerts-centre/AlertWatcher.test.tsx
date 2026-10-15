import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetchInbox: vi.fn(), toastError: vi.fn(), tone: vi.fn(), sound: { on: false } }));
vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), fetchInbox: mocks.fetchInbox }));
vi.mock("@/components/ui/sonner", () => ({ toast: { error: mocks.toastError } }));
vi.mock("./prefs", () => ({ readSoundPref: () => mocks.sound.on, playAlertTone: mocks.tone, writeSoundPref: vi.fn() }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { alertsInboxKey } from "./api";
import AlertWatcher from "./AlertWatcher";
import type { InboxAlert } from "./model";
import { alertRow } from "./testFixtures";

const BACKLOG = [alertRow({ id: 2, severity: "CRITICAL", message: "Old critical" }), alertRow({ id: 1, severity: "WARNING" })];

function setup(initial: InboxAlert[] = BACKLOG) {
  mocks.fetchInbox.mockResolvedValue(initial);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AlertWatcher />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}
const push = (client: QueryClient, rows: InboxAlert[]) => act(async () => void client.setQueryData(alertsInboxKey, rows));

beforeEach(() => {
  mocks.fetchInbox.mockReset();
  mocks.toastError.mockReset();
  mocks.tone.mockReset();
  mocks.sound.on = false;
});
afterEach(cleanup);

describe("AlertWatcher", () => {
  it("links to the alerts centre and states the open critical count in its name and text", async () => {
    setup();
    const link = await screen.findByRole("link", { name: "Alerts, 1 open critical" });
    expect(link).toHaveAttribute("href", "/alerts");
    expect(link).toHaveTextContent("Alerts · 1 critical");
  });

  it("does not announce the backlog that exists when the app opens", async () => {
    setup();
    await screen.findByRole("link", { name: /open critical/ });
    expect(mocks.toastError).not.toHaveBeenCalled();
    expect(screen.getByTestId("alert-announcer").textContent).toBe("");
  });

  it("a new critical alert raises ONE toast with an Open action, a live-region announcement, and no sound by default", async () => {
    const { client } = setup();
    await screen.findByRole("link", { name: /open critical/ });
    const fresh = alertRow({ id: 3, severity: "CRITICAL", message: "Coolant loop pressure drop" });
    await push(client, [fresh, ...BACKLOG]);
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledTimes(1));
    const [title, opts] = mocks.toastError.mock.calls[0] as [string, { description: string; action: { label: string } }];
    expect(title).toBe("Critical alert #3");
    expect(opts.description).toBe("Coolant loop pressure drop");
    expect(opts.action.label).toBe("Open");
    expect(screen.getByTestId("alert-announcer")).toHaveTextContent("New critical alert: Coolant loop pressure drop");
    expect(mocks.tone).not.toHaveBeenCalled();
    // the same data arriving again does not repeat it
    await push(client, [fresh, ...BACKLOG]);
    expect(mocks.toastError).toHaveBeenCalledTimes(1);
  });

  it("plays the tone only when the user turned sound on", async () => {
    mocks.sound.on = true;
    const { client } = setup();
    await screen.findByRole("link", { name: /open critical/ });
    await push(client, [alertRow({ id: 3, severity: "CRITICAL" }), ...BACKLOG]);
    await waitFor(() => expect(mocks.tone).toHaveBeenCalledTimes(1));
  });

  it("a new warning raises nothing, and a burst is summarised after three toasts", async () => {
    const { client } = setup();
    await screen.findByRole("link", { name: /open critical/ });
    await push(client, [alertRow({ id: 3, severity: "WARNING" }), ...BACKLOG]);
    expect(mocks.toastError).not.toHaveBeenCalled();

    const burst = [10, 11, 12, 13, 14].map((id) => alertRow({ id, severity: "CRITICAL" }));
    await push(client, [...burst, ...BACKLOG]);
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledTimes(4)); // three alerts + "2 more"
    expect(mocks.toastError.mock.calls[3][0]).toBe("2 more new critical alerts");
    expect(screen.getByTestId("alert-announcer")).toHaveTextContent("5 new critical alerts");
  });

  it("before any data it is just a plain link (no count is invented)", () => {
    mocks.fetchInbox.mockReturnValue(new Promise(() => {}));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AlertWatcher />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("link", { name: "Alerts" })).toBeInTheDocument();
  });
});
