/** Task 15: pure helpers for the assistant (no React, no network). */
import type { AskBody, ContextRef, Evidence, Freshness, HistoryItem, Mode, Origin } from "./schema";

export const LIMITS = { question: 500, historyItems: 6, historyText: 500, id: 64, answer: 1500 } as const;

export const modeLabel = (mode: Mode): string => (mode === "llm" ? "Model-phrased (evidence-checked)" : "Rule-based explanation");

export type BuiltRequest = { ok: true; body: AskBody } | { ok: false; reason: "empty" | "too_long" | "bad_context" };

/** The request for `POST /api/copilot/ask`: bounds are enforced here too (the server checks again). */
export function buildRequest(questionRaw: string, context: ContextRef, history: readonly HistoryItem[]): BuiltRequest {
  const question = questionRaw.trim();
  if (question === "") return { ok: false, reason: "empty" };
  if (question.length > LIMITS.question) return { ok: false, reason: "too_long" };
  if (context.id !== undefined && (context.id === "" || context.id.length > LIMITS.id)) return { ok: false, reason: "bad_context" };
  const kept = history.slice(-LIMITS.historyItems).map((h): HistoryItem => ({ role: h.role, text: h.text.slice(0, LIMITS.historyText) }));
  const ctx = context.id === undefined ? { kind: context.kind } : { kind: context.kind, id: context.id };
  return { ok: true, body: { question, context: ctx, history: kept } };
}

export type Segment = { type: "text"; text: string } | { type: "cite"; id: string };

/** Splits an answer at `[E#]` markers. A marker with no matching evidence stays plain text (it is not a citation). */
export function segmentsOf(answer: string, evidence: readonly Evidence[]): Segment[] {
  const known = new Set(evidence.map((e) => e.id));
  const out: Segment[] = [];
  let last = 0;
  for (const m of answer.matchAll(/\[(E\d{1,3})\]/g)) {
    const at = m.index ?? 0;
    if (!known.has(m[1])) continue;
    if (at > last) out.push({ type: "text", text: answer.slice(last, at) });
    out.push({ type: "cite", id: m[1] });
    last = at + m[0].length;
  }
  if (last < answer.length) out.push({ type: "text", text: answer.slice(last) });
  return out;
}

/** Route patterns that take one id segment. Everything else must match a known route exactly. */
const ID_ROUTES = ["/runs", "/evaluation"] as const;
const SAFE_PATH = /^\/[A-Za-z0-9._~\-/]*(\?[A-Za-z0-9._~\-=&%]*)?$/;

/** A link from `links[]` is followed only when it is a relative path to a route this app has. Anything else is text. */
export function isSafeLink(path: string, knownRoutes: readonly string[]): boolean {
  if (!SAFE_PATH.test(path) || path.startsWith("//") || path.includes("..")) return false;
  const pathname = path.split("?")[0];
  const clean = pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  if (knownRoutes.includes(clean)) return true;
  return ID_ROUTES.some((r) => clean.startsWith(`${r}/`) && clean.slice(r.length + 1).length > 0 && !clean.slice(r.length + 1).includes("/"));
}

export const FRESHNESS_VIEW: Readonly<Record<Freshness, { text: string; note: string }>> = {
  fresh: { text: "Fresh", note: "recent" },
  stale: { text: "Stale", note: "older than expected" },
  unavailable: { text: "Unavailable", note: "could not be read" },
  static: { text: "Static", note: "documentation, does not change with time" },
};

export const ORIGIN_VIEW: Readonly<Record<Origin, string>> = {
  simulated: "Simulated",
  measured: "Measured",
  replayed: "Replayed",
  assumed: "Assumed",
  documentation: "Documentation",
  unknown: "Unknown origin",
};

export const hasWeakEvidence = (evidence: readonly Evidence[]): boolean => evidence.some((e) => e.freshness === "stale" || e.freshness === "unavailable");

export function valueText(e: Evidence): string {
  if (e.value === null) return "no value";
  const v = typeof e.value === "number" ? String(Math.round(e.value * 10000) / 10000) : String(e.value);
  return e.unit ? `${v} ${e.unit}` : v;
}

/** `2026-10-20T03:10:00Z` -> `2026-10-20 03:10 UTC`; anything else is shown as sent. */
export function observedText(iso: string | null): string {
  if (iso === null) return "n/a";
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?Z$/.exec(iso);
  return m ? `${m[1]} ${m[2]} UTC` : iso;
}

const WARNING_TEXT: Readonly<Record<string, string>> = {
  llm_unavailable: "The language model was unavailable, so this is the rule-based answer.",
  llm_rejected: "The model's wording was rejected because it used a number the evidence does not back, so this is the rule-based answer.",
};
/** Known warning codes get a sentence; an unknown code is shown as received (text only). */
export const warningText = (code: string): string => WARNING_TEXT[code] ?? code;

export type AssistantErrorKind = "offline" | "rate_limited" | "not_found" | "invalid" | "unauthenticated" | "unavailable" | "contract" | "other";

export const ERROR_COPY: Readonly<Record<AssistantErrorKind, { title: string; text: string; retry: boolean }>> = {
  offline: { title: "You are offline", text: "The assistant needs a connection. Nothing was sent.", retry: true },
  rate_limited: { title: "Too many questions", text: "Please wait a moment before asking again.", retry: true },
  not_found: { title: "Not found", text: "The thing you asked about no longer exists or was never recorded.", retry: false },
  invalid: { title: "That question cannot be sent", text: "Check the length of the question and try again.", retry: false },
  unauthenticated: { title: "Please sign in again", text: "Your session ended.", retry: false },
  unavailable: { title: "The assistant is unavailable", text: "The service did not answer. This is not an answer about your system.", retry: true },
  contract: { title: "The reply could not be read", text: "The service sent something this page does not understand, so nothing is shown.", retry: true },
  other: { title: "Something went wrong", text: "The question could not be answered.", retry: true },
};

export function errorKindOf(kind: string | undefined): AssistantErrorKind {
  switch (kind) {
    case "network":
      return "offline";
    case "rate_limited":
    case "not_found":
    case "unauthenticated":
    case "unavailable":
    case "contract":
      return kind;
    case "validation":
      return "invalid";
    default:
      return "other";
  }
}

/** Starter questions per context. Plain strings: they are the user's to edit before sending. */
export function suggestionsFor(c: ContextRef): string[] {
  switch (c.kind) {
    case "alert":
      return ["Why is this alert red?", "What changed?", "What can I check next?"];
    case "signal":
      return ["What is the current status of this signal?", "What does this signal mean?"];
    case "model":
      return ["What are this model's limits?", "What is this model?"];
    default:
      return ["What can this system tell me?"];
  }
}
