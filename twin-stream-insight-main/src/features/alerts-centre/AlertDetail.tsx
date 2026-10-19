import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { SeverityBadge, StatusBadge } from "./badges";
import { changeErrorText } from "./errors";
import { ACTION_LABEL, MAX_ASSIGNEE_CHARS, MAX_NOTE_CHARS, formatUtc, nextStatuses, replayHref, type AlertPatch, type InboxAlert } from "./model";
import { Timeline } from "./Timeline";
import { AlertExplanation } from "../explainability/AlertExplanation";

interface Props {
  alert: InboxAlert;
  isOperator: boolean;
  /** Sends one change; resolves to the server's row or throws. */
  apply: (id: number, patch: AlertPatch) => Promise<unknown>;
}

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-xs">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="break-words text-right">{children}</dd>
    </div>
  );
}

export function AlertDetail({ alert, isOperator, apply }: Props) {
  const { username } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [assignee, setAssignee] = useState("");
  const [note, setNote] = useState("");

  async function run(patch: AlertPatch, success: string, after?: () => void) {
    setPending(true);
    setError(null);
    setDone(null);
    try {
      await apply(alert.id, patch);
      setDone(success);
      after?.();
    } catch (e) {
      setError(changeErrorText(e));
    } finally {
      setPending(false);
    }
  }

  const replay = replayHref(alert.created_at);
  const trimmedAssignee = assignee.trim();
  const trimmedNote = note.trim();

  return (
    <article aria-label={`Alert ${alert.id}`} data-testid="alert-detail" className="space-y-4 rounded-md border border-border bg-card p-3">
      <header className="space-y-1.5">
        <h2 className="text-sm font-semibold">Alert #{alert.id}</h2>
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={alert.severity} />
          <StatusBadge status={alert.status} />
        </div>
        <p className="break-words text-sm">{alert.message}</p>
      </header>

      <dl className="space-y-1">
        <Fact label="Raised">{formatUtc(alert.created_at)}</Fact>
        <Fact label="Type">{alert.type}</Fact>
        <Fact label="Detector score">{alert.score}</Fact>
        <Fact label="Data origin">{alert.origin ?? "not recorded (written before provenance existed)"}</Fact>
        {alert.model_version ? <Fact label="Model version">{alert.model_version}</Fact> : null}
        <Fact label="Assignee">{alert.assignee ?? "unassigned"}</Fact>
        {alert.acknowledged_by ? (
          <Fact label="Acknowledged">
            {alert.acknowledged_by}, {formatUtc(alert.acknowledged_at)}
          </Fact>
        ) : null}
        {alert.resolved_by ? (
          <Fact label="Resolved">
            {alert.resolved_by}, {formatUtc(alert.resolved_at)}
          </Fact>
        ) : null}
      </dl>

      <nav aria-label="Where this alert happened" className="space-y-1 text-xs">
        <div className="flex flex-wrap gap-2">
          <Link to="/" className={BTN}>
            Open facility view
          </Link>
          {replay ? (
            <Link to={replay} className={BTN}>
              Open this moment in Replay
            </Link>
          ) : null}
        </div>
        <p className="text-muted-foreground">The backend does not attribute an alert to a rack, so the facility link opens the whole facility, not one rack.</p>
      </nav>

      {isOperator ? (
        <section aria-label="Change this alert" className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {nextStatuses(alert.status).map((s) => (
              <button key={s} type="button" disabled={pending} className={BTN} onClick={() => void run({ status: s }, `Alert ${alert.id} is now ${s}.`)}>
                {ACTION_LABEL[s]}
              </button>
            ))}
          </div>

          <form
            className="space-y-1.5"
            onSubmit={(ev: FormEvent) => {
              ev.preventDefault();
              if (trimmedAssignee) void run({ assignee: trimmedAssignee }, `Assigned to ${trimmedAssignee}.`, () => setAssignee(""));
            }}
          >
            <label htmlFor={`assignee-${alert.id}`} className="block text-xs text-muted-foreground">
              Assignee (an operator's username)
            </label>
            <div className="flex flex-wrap gap-2">
              <input
                id={`assignee-${alert.id}`}
                value={assignee}
                maxLength={MAX_ASSIGNEE_CHARS}
                onChange={(e) => setAssignee(e.target.value)}
                className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <button type="submit" disabled={pending || !trimmedAssignee} className={BTN}>
                Assign
              </button>
              {username && username !== alert.assignee ? (
                <button type="button" disabled={pending} className={BTN} onClick={() => void run({ assignee: username }, "Assigned to you.")}>
                  Assign to me
                </button>
              ) : null}
              {alert.assignee ? (
                <button type="button" disabled={pending} className={BTN} onClick={() => void run({ assignee: null }, "Unassigned.")}>
                  Unassign
                </button>
              ) : null}
            </div>
          </form>

          <form
            className="space-y-1.5"
            onSubmit={(ev: FormEvent) => {
              ev.preventDefault();
              if (trimmedNote) void run({ note: trimmedNote }, "Note added.", () => setNote(""));
            }}
          >
            <label htmlFor={`note-${alert.id}`} className="block text-xs text-muted-foreground">
              Add a note to the timeline
            </label>
            <textarea
              id={`note-${alert.id}`}
              value={note}
              maxLength={MAX_NOTE_CHARS}
              rows={2}
              onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <button type="submit" disabled={pending || !trimmedNote} className={BTN}>
              Add note
            </button>
          </form>

          <div aria-live="polite" className="min-h-[1rem] text-xs">
            {pending ? <span role="status">Saving…</span> : null}
            {done && !pending ? <span role="status">{done}</span> : null}
            {error ? (
              <span role="alert" className="text-destructive-text">
                {error}
              </span>
            ) : null}
          </div>
        </section>
      ) : (
        <p className="text-xs text-muted-foreground">Read-only: changing, assigning or annotating alerts needs the operator role.</p>
      )}

      <AlertExplanation alertId={alert.id} />

      <Timeline alertId={alert.id} />
    </article>
  );
}
