import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, Loader2, WifiOff } from "lucide-react";
import { isApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useReturnFocus } from "@/lib/returnFocus";
import { askCopilot } from "./api";
import { AnswerView } from "./AnswerView";
import { ASK_TIMEOUT_MS, ERROR_COPY, LIMITS, SLOW_AFTER_MS, buildRequest, errorKindOf, modeLabel, providerText, suggestionsFor, type AssistantErrorKind } from "./model";
import type { ContextRef, CopilotResponse, HistoryItem } from "./schema";

export type Ask = (body: Parameters<typeof askCopilot>[0], signal?: AbortSignal) => Promise<CopilotResponse>;

type Outcome = { type: "pending" } | { type: "answer"; data: CopilotResponse } | { type: "error"; kind: AssistantErrorKind; retryAfterS?: number };
interface Turn {
  id: number;
  question: string;
  outcome: Outcome;
}

const CONTEXT_TITLE: Record<ContextRef["kind"], string> = { alert: "Alert", signal: "Signal", model: "Model", feature: "Feature", general: "This system" };
const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Client-held history for the next request: the answered turns as user/assistant items, newest last, at most 6. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper exported for tests; only costs a full reload in dev
export function historyOf(turns: readonly Turn[]): HistoryItem[] {
  const items: HistoryItem[] = [];
  for (const t of turns) {
    if (t.outcome.type !== "answer") continue;
    items.push({ role: "user", text: t.question }, { role: "assistant", text: t.outcome.data.answer });
  }
  return items.slice(-LIMITS.historyItems);
}

/** A question in flight: the plain wait text, a slow-path note after `slowAfterMs` (local models are slower), and Cancel. */
function PendingTurn({ slowAfterMs, onCancel }: { slowAfterMs: number; onCancel: () => void }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), slowAfterMs);
    return () => clearTimeout(t);
  }, [slowAfterMs]);
  return (
    <div className="space-y-1.5" data-testid="turn-pending">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
        Looking up the evidence…
      </p>
      {slow ? (
        <p role="status" data-testid="turn-slow" className="text-xs text-muted-foreground">
          This is taking longer than usual. A local model can be slow. You can wait or cancel; nothing is changed either way.
        </p>
      ) : null}
      <button type="button" className={BTN} onClick={onCancel} data-testid="turn-cancel">
        Cancel
      </button>
    </div>
  );
}

interface ConversationProps {
  context: ContextRef;
  ask: Ask;
  knownRoutes: readonly string[];
  onClose: () => void;
  timeoutMs: number;
  slowAfterMs: number;
}

function Conversation({ context, ask, knownRoutes, onClose, timeoutMs, slowAfterMs }: ConversationProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const nextId = useRef(1);
  const turnsRef = useRef<Turn[]>([]);
  const controller = useRef<AbortController | null>(null);
  const started = useRef(false);
  const cancelPending = useRef<(() => void) | null>(null);
  turnsRef.current = turns;

  const setOutcome = (id: number, outcome: Outcome) => setTurns((all) => all.map((t) => (t.id === id ? { ...t, outcome } : t)));

  async function submit(questionRaw: string, replaceId?: number) {
    const built = buildRequest(questionRaw, context, historyOf(turnsRef.current.filter((t) => t.id !== replaceId)));
    if (built.ok === false) {
      setFormError(built.reason === "empty" ? "Type a question first." : built.reason === "too_long" ? `Questions are limited to ${LIMITS.question} characters.` : "This item cannot be asked about.");
      return;
    }
    setFormError(null);
    const id = replaceId ?? nextId.current++;
    const question = built.body.question;
    setTurns((all) => (replaceId === undefined ? [...all, { id, question, outcome: { type: "pending" } }] : all.map((t) => (t.id === id ? { ...t, outcome: { type: "pending" } } : t))));
    setDraft("");
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setOutcome(id, { type: "error", kind: "offline" });
      setAnnounce(ERROR_COPY.offline.title);
      return;
    }
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    // `stop` is the only abort that shows an outcome ("cancel" = the button, "timeout" = the client limit). Any other abort is a superseded or closed turn and shows nothing.
    const stop = (reason: "cancel" | "timeout") => {
      if (ctl.signal.aborted) return;
      ctl.abort();
      const kind: AssistantErrorKind = reason === "cancel" ? "cancelled" : "timeout";
      setOutcome(id, { type: "error", kind });
      setAnnounce(ERROR_COPY[kind].title);
    };
    cancelPending.current = () => stop("cancel");
    const timer = setTimeout(() => stop("timeout"), timeoutMs);
    try {
      const data = await ask(built.body, ctl.signal);
      if (ctl.signal.aborted) return;
      setOutcome(id, { type: "answer", data });
      const from = providerText(data);
      const sources = data.citations?.length ?? 0;
      setAnnounce(`Answer received. ${modeLabel(data.mode)}${from ? ` (${from})` : ""}. ${data.evidence.length} evidence items.${sources > 0 ? ` ${sources} sources cited.` : ""}`);
    } catch (e) {
      if (ctl.signal.aborted) return; // `stop` already showed the outcome; any other abort is a superseded turn
      const kind: AssistantErrorKind = e instanceof AuthRequiredError ? "unauthenticated" : errorKindOf(isApiError(e) ? e.kind : undefined);
      setOutcome(id, { type: "error", kind, retryAfterS: isApiError(e) ? e.retryAfterS : undefined });
      setAnnounce(ERROR_COPY[kind].title);
    } finally {
      clearTimeout(timer);
      if (controller.current === ctl) cancelPending.current = null;
    }
  }

  // Opening for one alert, signal or model asks the first suggested question straight away (once).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (context.kind !== "general") void submit(suggestionsFor(context)[0]);
    return () => controller.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per opening; `submit` closes over refs and setters only
  }, []);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit(draft);
  };
  const busy = turns.some((t) => t.outcome.type === "pending");

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div role="status" aria-live="polite" className="sr-only" data-testid="assistant-live">
        {announce}
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto pr-1" data-testid="assistant-turns">
        {turns.length === 0 ? <p className="text-xs text-muted-foreground">Ask about what this system shows. Answers cite their evidence; where evidence is missing they say so.</p> : null}
        {turns.map((t) => (
          <article key={t.id} aria-label={`Question ${t.id}`} className="space-y-2" data-testid="turn">
            <p className="rounded bg-muted px-2 py-1 text-xs font-medium" data-testid="turn-question">
              {t.question}
            </p>
            {t.outcome.type === "pending" ? (
              <PendingTurn slowAfterMs={slowAfterMs} onCancel={() => cancelPending.current?.()} />
            ) : t.outcome.type === "answer" ? (
              <AnswerView turnId={t.id} data={t.outcome.data} knownRoutes={knownRoutes} onNavigate={onClose} />
            ) : (
              <div role="alert" data-testid="turn-error" data-kind={t.outcome.kind} className="space-y-1 rounded border border-destructive/50 p-2 text-xs">
                <p className="flex items-center gap-1.5 font-semibold">
                  {t.outcome.kind === "offline" ? <WifiOff aria-hidden="true" className="h-3.5 w-3.5" /> : <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5" />}
                  {ERROR_COPY[t.outcome.kind].title}
                </p>
                <p>
                  {ERROR_COPY[t.outcome.kind].text}
                  {t.outcome.kind === "rate_limited" && t.outcome.retryAfterS ? ` Try again in about ${t.outcome.retryAfterS} seconds.` : ""}
                </p>
                {ERROR_COPY[t.outcome.kind].retry ? (
                  <button type="button" className={BTN} onClick={() => void submit(t.question, t.id)} data-testid="turn-retry">
                    Retry
                  </button>
                ) : null}
              </div>
            )}
          </article>
        ))}
      </div>

      {turns.length === 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Suggested questions">
          {suggestionsFor(context).map((s) => (
            <li key={s}>
              <button type="button" className={BTN} onClick={() => setDraft(s)}>
                {s}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <form onSubmit={onSubmit} className="space-y-1.5" aria-label="Ask a question">
        <label htmlFor="assistant-question" className="text-xs font-medium">
          Your question
        </label>
        <textarea
          id="assistant-question"
          data-testid="assistant-input"
          value={draft}
          maxLength={LIMITS.question + 50}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          className="w-full rounded-md border border-border bg-background p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div className="flex items-center justify-between gap-2">
          <span className={`text-[11px] ${draft.length > LIMITS.question ? "text-destructive" : "text-muted-foreground"}`}>
            {draft.length}/{LIMITS.question}
          </span>
          <button type="submit" className={BTN} disabled={busy} data-testid="assistant-send">
            Ask
          </button>
        </div>
        {formError ? (
          <p role="alert" className="text-xs text-destructive" data-testid="assistant-form-error">
            {formError}
          </p>
        ) : null}
      </form>
    </div>
  );
}

interface Props {
  open: boolean;
  context: ContextRef;
  /** Changes on every opening: a new opening starts a new conversation. */
  nonce: number;
  onClose: () => void;
  knownRoutes: readonly string[];
  ask?: Ask;
  /** CP-10: abort a question after this long (default {@link ASK_TIMEOUT_MS}). Tests set it small. */
  timeoutMs?: number;
  /** CP-10: show the slow-path note after this long (default {@link SLOW_AFTER_MS}). */
  slowAfterMs?: number;
}

/** The assistant drawer: a Radix dialog, so focus is trapped, Esc closes it and useReturnFocus gives focus back to the button that opened it (the drawer has no Radix trigger). */
export function AssistantDrawer({ open, context, nonce, onClose, knownRoutes, ask = askCopilot, timeoutMs = ASK_TIMEOUT_MS, slowAfterMs = SLOW_AFTER_MS }: Props) {
  const returnFocus = useReturnFocus();
  return (
    <Sheet open={open} onOpenChange={(o) => (o ? undefined : onClose())}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-xl" data-testid="assistant-drawer" {...returnFocus}>
        <SheetHeader>
          <SheetTitle>Assistant: {CONTEXT_TITLE[context.kind]}{context.id ? ` ${context.id}` : ""}</SheetTitle>
          <SheetDescription>Explains what this system shows, from evidence. It does not change anything.</SheetDescription>
        </SheetHeader>
        {open ? <Conversation key={nonce} context={context} ask={ask} knownRoutes={knownRoutes} onClose={onClose} timeoutMs={timeoutMs} slowAfterMs={slowAfterMs} /> : null}
      </SheetContent>
    </Sheet>
  );
}
