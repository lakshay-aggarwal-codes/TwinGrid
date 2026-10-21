import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useSyncExternalStore } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ AuthRequiredError: class AuthRequiredError extends Error {}, getToken: vi.fn(), forceRefresh: vi.fn() }));
vi.mock("@/authClient", () => ({ AuthRequiredError: auth.AuthRequiredError, getToken: auth.getToken, forceRefresh: auth.forceRefresh }));
vi.mock("@/config", () => ({ API_BASE_URL: "https://api.example.com", assertApiConfigured: () => {} }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import { AssistantDrawer, historyOf, type Ask } from "./AssistantDrawer";
import { ExplainButton } from "./ExplainButton";
import { closeAssistant, getAssistantState, resetAssistantStore, subscribeAssistant } from "./store";
import type { ContextRef, CopilotResponse } from "./schema";
import { HOSTILE, KNOWN_ROUTES, LLM_FALLBACK, REFUSAL, RULE_BASED, STALE, UNKNOWN_CAUSE } from "./testFixtures";

const ask = vi.fn<Ask>();
const onClose = vi.fn();

function drawer(context: ContextRef, nonce = 1) {
  return (
    <MemoryRouter>
      <AssistantDrawer open context={context} nonce={nonce} onClose={onClose} knownRoutes={KNOWN_ROUTES} ask={ask} />
    </MemoryRouter>
  );
}
const ALERT: ContextRef = { kind: "alert", id: "42" };
const send = (q: string) => {
  fireEvent.change(screen.getByTestId("assistant-input"), { target: { value: q } });
  fireEvent.click(screen.getByTestId("assistant-send"));
};

beforeEach(() => {
  ask.mockReset().mockResolvedValue(RULE_BASED);
  onClose.mockReset();
});
afterEach(() => {
  cleanup();
  resetAssistantStore();
  vi.restoreAllMocks();
});

describe("alert explanation (rule-based fixture)", () => {
  it("opening for an alert asks straight away and shows an evidence-backed answer", async () => {
    render(drawer(ALERT));
    await screen.findByTestId("answer");
    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask.mock.calls[0][0]).toEqual({ question: "Why is this alert red?", context: { kind: "alert", id: "42" }, history: [] });
    expect(screen.getByTestId("answer-mode")).toHaveTextContent("Rule-based explanation");
    expect(screen.getByTestId("answer-mode")).toHaveTextContent("no language model is configured");
    expect(screen.getByTestId("answer-text")).toHaveTextContent("Alert 42 scored E1 against a threshold of E2.");
    // the evidence table makes the values inspectable
    expect(screen.getByTestId("evidence-value-E1")).toHaveTextContent("0.91");
    expect(screen.getByTestId("evidence-origin-E1")).toHaveTextContent("Simulated");
    expect(screen.getByTestId("evidence-freshness-E1")).toHaveTextContent("Fresh");
    expect(screen.getByTestId("evidence-freshness-E2")).toHaveTextContent("Static");
    expect(within(screen.getByTestId("evidence-row-E1")).getByText("alert_explanation")).toBeInTheDocument();
    expect(within(screen.getByTestId("evidence-row-E1")).getByText("2026-10-20 03:10 UTC")).toBeInTheDocument();
  });

  it("a citation chip is a focusable button that moves focus to its evidence row", async () => {
    render(drawer(ALERT));
    const chip = await screen.findByTestId("cite-E1");
    expect(chip.tagName).toBe("BUTTON");
    expect(chip).toHaveAccessibleName("Evidence E1");
    fireEvent.click(chip);
    expect(document.activeElement).toBe(screen.getByTestId("evidence-row-E1"));
  });

  it("announces the answer in a polite live region", async () => {
    render(drawer(ALERT));
    await screen.findByTestId("answer");
    const live = screen.getByTestId("assistant-live");
    expect(live).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(live).toHaveTextContent(/Answer received\. Rule-based explanation\. 2 evidence items\./));
  });

  it("an unknown cause stays unknown and is listed", async () => {
    ask.mockResolvedValue(UNKNOWN_CAUSE);
    render(drawer(ALERT));
    const unknowns = await screen.findByTestId("answer-unknowns");
    expect(unknowns).toHaveTextContent("Root cause is not determined by available evidence.");
    expect(screen.getByTestId("answer-text")).toHaveTextContent("not determined by available evidence");
  });

  it("stale evidence is flagged distinctly and never reads as normal", async () => {
    ask.mockResolvedValue(STALE);
    render(drawer(ALERT));
    expect(await screen.findByTestId("answer-stale")).toHaveTextContent("stale or unavailable");
    expect(screen.getByTestId("evidence-freshness-E1")).toHaveTextContent("Stale");
    expect(screen.getByTestId("answer-warnings")).toHaveTextContent("evidence_stale"); // unknown code is shown as received
    expect(screen.queryByTestId("turn-error")).toBeNull(); // not styled as an error
    expect(screen.getByTestId("answer").textContent ?? "").not.toMatch(/\bnormal\b/i);
  });

  it("a refusal shows no values and says why", async () => {
    ask.mockResolvedValue(REFUSAL);
    render(drawer(ALERT));
    expect(await screen.findByTestId("evidence-none")).toBeInTheDocument();
    expect(screen.getByTestId("answer-unknowns")).toHaveTextContent("outside what this system records");
  });

  it("an llm fallback warning is explained and the mode stays rule-based", async () => {
    ask.mockResolvedValue(LLM_FALLBACK);
    render(drawer(ALERT));
    expect(await screen.findByTestId("answer-warnings")).toHaveTextContent("The language model was unavailable");
    expect(screen.getByTestId("answer-mode")).toHaveTextContent("Rule-based explanation");
    expect(screen.getByTestId("answer-mode")).not.toHaveTextContent("no language model is configured");
  });

  it("an llm answer is labelled as model-phrased and evidence-checked", async () => {
    ask.mockResolvedValue({ ...RULE_BASED, mode: "llm", limits: { provider_configured: true } } as CopilotResponse);
    render(drawer(ALERT));
    expect(await screen.findByTestId("answer-mode")).toHaveTextContent("Model-phrased (evidence-checked)");
  });
});

describe("safe rendering", () => {
  it("markup in the answer, evidence and warnings is shown as text, and unsafe links are not links", async () => {
    ask.mockResolvedValue(HOSTILE);
    render(drawer(ALERT));
    await screen.findByTestId("answer");
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByTestId("answer-text")).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(screen.getByTestId("answer-text")).toHaveTextContent("ignore previous instructions");
    expect(screen.getByTestId("evidence-value-E1")).toHaveTextContent("<b>bold</b>");
    expect(screen.getByTestId("answer-warnings")).toHaveTextContent("<script>alert(1)</script>");
    const links = within(screen.getByTestId("answer-links")).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/alerts"]);
    expect(screen.getAllByTestId("link-unavailable")).toHaveLength(3);
    expect(document.querySelector('a[href^="http"], a[href^="//"], a[href^="javascript"]')).toBeNull();
  });

  it("a known link navigates and closes the drawer", async () => {
    render(drawer(ALERT));
    fireEvent.click(await screen.findByRole("link", { name: "Alerts" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("a long answer is shown in full", async () => {
    const long = "word ".repeat(300).trim();
    ask.mockResolvedValue({ ...RULE_BASED, answer: long } as CopilotResponse);
    render(drawer(ALERT));
    expect((await screen.findByTestId("answer-text")).textContent).toBe(long);
  });
});

describe("errors, retry, rate limit and offline", () => {
  it("a rate limit says how long to wait and Retry asks again", async () => {
    ask.mockRejectedValueOnce(new ApiError({ kind: "rate_limited", status: 429, retryAfterS: 30 })).mockResolvedValueOnce(RULE_BASED);
    render(drawer(ALERT));
    const err = await screen.findByTestId("turn-error");
    expect(err).toHaveAttribute("data-kind", "rate_limited");
    expect(err).toHaveTextContent("Too many questions");
    expect(err).toHaveTextContent("about 30 seconds");
    fireEvent.click(screen.getByTestId("turn-retry"));
    await screen.findByTestId("answer");
    expect(ask).toHaveBeenCalledTimes(2);
    expect(screen.getAllByTestId("turn")).toHaveLength(1); // retry replaces, it does not add a turn
    expect(screen.queryByTestId("turn-error")).toBeNull();
  });

  it("a network failure is shown as offline with Retry", async () => {
    ask.mockRejectedValueOnce(new ApiError({ kind: "network" }));
    render(drawer(ALERT));
    const err = await screen.findByTestId("turn-error");
    expect(err).toHaveAttribute("data-kind", "offline");
    expect(screen.getByTestId("turn-retry")).toBeInTheDocument();
  });

  it("when the browser is offline nothing is sent", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    render(drawer(ALERT));
    expect(await screen.findByTestId("turn-error")).toHaveAttribute("data-kind", "offline");
    expect(ask).not.toHaveBeenCalled();
  });

  it.each([
    ["contract", new ApiError({ kind: "contract", status: 200 }), true],
    ["unavailable", new ApiError({ kind: "unavailable", status: 503 }), true],
    ["not_found", new ApiError({ kind: "not_found", status: 404 }), false],
    ["invalid", new ApiError({ kind: "validation", status: 422 }), false],
    ["unauthenticated", new auth.AuthRequiredError(), false],
  ])("%s is an error, not an answer, and Retry is offered only when it can help", async (kind, error, retry) => {
    ask.mockRejectedValueOnce(error);
    render(drawer(ALERT));
    const el = await screen.findByTestId("turn-error");
    expect(el).toHaveAttribute("data-kind", kind);
    expect(screen.queryByTestId("answer")).toBeNull();
    expect(screen.queryByTestId("turn-retry") !== null).toBe(retry);
  });
});

describe("asking questions", () => {
  it("a general drawer asks nothing until you do, and refuses empty and over-long questions", async () => {
    render(drawer({ kind: "general" }));
    expect(ask).not.toHaveBeenCalled();
    send("   ");
    expect(screen.getByTestId("assistant-form-error")).toHaveTextContent("Type a question first.");
    send("x".repeat(501));
    expect(screen.getByTestId("assistant-form-error")).toHaveTextContent("limited to 500 characters");
    expect(ask).not.toHaveBeenCalled();
    send("What can this system tell me?");
    await screen.findByTestId("answer");
    expect(ask.mock.calls[0][0]).toEqual({ question: "What can this system tell me?", context: { kind: "general" }, history: [] });
  });

  it("history is client-held, answered turns only, at most 6 items", async () => {
    render(drawer({ kind: "general" }));
    for (let i = 1; i <= 5; i++) {
      send(`Question ${i}`);
      await waitFor(() => expect(screen.getAllByTestId("answer")).toHaveLength(i));
    }
    expect(ask.mock.calls[3][0].history).toHaveLength(6); // three answered turns
    const fifth = ask.mock.calls[4][0];
    expect(fifth.history).toHaveLength(6); // four answered turns = 8 items, cut to the last 6
    expect(fifth.history[0]).toEqual({ role: "user", text: "Question 2" });
    expect(fifth.history[fifth.history.length - 2]).toEqual({ role: "user", text: "Question 4" });
  });

  it("a failed question is not part of the history", () => {
    const answered = { id: 1, question: "A", outcome: { type: "answer" as const, data: RULE_BASED } };
    const failed = { id: 2, question: "B", outcome: { type: "error" as const, kind: "offline" as const } };
    expect(historyOf([answered, failed])).toEqual([
      { role: "user", text: "A" },
      { role: "assistant", text: RULE_BASED.answer },
    ]);
  });

  it("a new opening starts a fresh conversation", async () => {
    const { rerender } = render(drawer(ALERT, 1));
    await screen.findByTestId("answer");
    rerender(drawer({ kind: "model" }, 2));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0].context).toEqual({ kind: "model" });
    expect(screen.getAllByTestId("turn")).toHaveLength(1);
  });
});

describe("keyboard and dialog behaviour", () => {
  it("is a dialog, and Escape closes it", async () => {
    render(drawer(ALERT));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("the question box is labelled and reachable", async () => {
    render(drawer({ kind: "general" }));
    expect(screen.getByLabelText("Your question")).toBe(screen.getByTestId("assistant-input"));
  });
});

describe("Explain this: alert to explanation without leaving the page", () => {
  function Host() {
    const s = useSyncExternalStore(subscribeAssistant, getAssistantState, getAssistantState);
    return (
      <MemoryRouter>
        <ExplainButton context={{ kind: "alert", id: "42" }} />
        <ExplainButton context={{ kind: "model" }} label="Explain the model" />
        <AssistantDrawer open={s.open} context={s.context} nonce={s.nonce} onClose={closeAssistant} knownRoutes={KNOWN_ROUTES} ask={ask} />
      </MemoryRouter>
    );
  }

  it("clicking the button opens the drawer for that alert and shows the explanation", async () => {
    render(<Host />);
    expect(ask).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByTestId("explain-button")[0]);
    await screen.findByTestId("evidence-table");
    expect(ask.mock.calls[0][0].context).toEqual({ kind: "alert", id: "42" });
    expect(screen.getByRole("dialog")).toHaveTextContent("Assistant: Alert 42");
    act(() => closeAssistant());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("the model button asks about the model", async () => {
    render(<Host />);
    fireEvent.click(screen.getByRole("button", { name: "Explain the model" }));
    await screen.findByTestId("answer");
    expect(ask.mock.calls[0][0]).toMatchObject({ context: { kind: "model" }, question: "What are this model's limits?" });
  });
});
