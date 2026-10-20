/**
 * Task 12: the access-request queue inside the admin console. The owner reviews who asked for viewer access, approves or
 * rejects (with an optional admin-only note), and can resend the owner notification or the activation email. It is mounted only
 * on the admin-only tab; the backend answers 403 to anyone else regardless. Tokens are never requested, held or shown.
 */
import { useRef, useState } from "react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { isApiError } from "@/api/apiError";
import { StateBoundary } from "@/state/StateBoundary";
import type { AccessDecision } from "./api";
import { actionErrorText } from "./errors";
import {
  ACCESS_STATUSES,
  NOTE_MAX_CHARS,
  accessQuery,
  accessStatusLabel,
  canDecide,
  canResendActivation,
  canResendNotification,
  expiresText,
  notifyLabel,
  parseNote,
  utcText,
  type AccessFilter,
} from "./model";
import type { AccessRequest } from "./schema";
import { FIELD, SECTION } from "./shared";
import { useAccessActions, useAccessRequest, useAccessRequests } from "./useAccessRequests";

/** Touch-friendly: at least 44 px tall and wide, unlike the compact BTN used in the desktop tables. */
const TOUCH_BTN =
  "min-h-11 min-w-11 rounded-md border border-border bg-background px-4 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const FILTERS: AccessFilter[] = [...ACCESS_STATUSES, "all"];
const filterLabel = (f: AccessFilter): string => (f === "all" ? "All" : accessStatusLabel(f));

/** Wording for a failed access action. Only the error kind selects it; the server's text is never shown. */
function accessErrorText(e: unknown, what: string): string {
  if (isApiError(e)) {
    if (e.kind === "conflict") return "This request was already decided or is no longer pending. The list has been refreshed.";
    if (e.kind === "not_found") return "That request no longer exists. The list has been refreshed.";
    if (e.kind === "validation") return "Not accepted. Shorten the note and try again.";
  }
  return actionErrorText(e, what);
}

interface Handlers {
  onDecide: (item: AccessRequest, decision: AccessDecision, trigger: HTMLElement) => void;
  onResend: (item: AccessRequest, kind: "notification" | "activation") => void;
  busyKey: string | null;
}

function Detail({ id }: { id: string }) {
  const { state, refetch } = useAccessRequest(id, true);
  return (
    <div className="mt-2 text-xs text-foreground" data-testid={`access-${id}-detail`}>
      <StateBoundary state={state} onRetry={refetch} block={false} messages={{ loading: "Loading details…" }}>
        {(r) => (
          <p>
            <span className="font-medium">Decision note (admin only): </span>
            <span className="break-words" data-testid={`access-${id}-note`}>{r.decision_note ? r.decision_note : "none"}</span>
          </p>
        )}
      </StateBoundary>
    </div>
  );
}

function RequestCard({ item, h }: { item: AccessRequest; h: Handlers }) {
  const [open, setOpen] = useState(false);
  const disabled = h.busyKey !== null;
  return (
    <li className="space-y-2 rounded-lg border border-border p-3" data-testid={`access-${item.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="break-words text-sm font-semibold text-foreground">{item.name}</h3>
        <span className="rounded border border-border px-2 py-0.5 text-xs font-medium text-foreground" data-testid={`access-${item.id}-status`}>
          {accessStatusLabel(item.status)}
        </span>
      </div>
      <dl className="grid grid-cols-1 gap-1 text-xs text-foreground">
        <div><dt className="inline text-muted-foreground">Email: </dt><dd className="inline break-all">{item.email}</dd></div>
        <div><dt className="inline text-muted-foreground">Reference: </dt><dd className="inline font-mono">{item.ref}</dd></div>
        <div><dt className="inline text-muted-foreground">Purpose: </dt><dd className="inline break-words">{item.purpose ? item.purpose : "none given"}</dd></div>
        <div><dt className="inline text-muted-foreground">Received: </dt><dd className="inline">{utcText(item.created_at)}</dd></div>
        <div><dt className="inline text-muted-foreground">Expires: </dt><dd className="inline" data-testid={`access-${item.id}-expires`}>{expiresText(item.expires_at, Date.now())}</dd></div>
        {item.decided_at && (
          <div>
            <dt className="inline text-muted-foreground">Decided: </dt>
            <dd className="inline">{utcText(item.decided_at)}{item.decided_by !== null ? ` by user #${item.decided_by}` : ""}</dd>
          </div>
        )}
        <div>
          <dt className="inline text-muted-foreground">Email status: </dt>
          <dd className="inline" data-testid={`access-${item.id}-notify`}>{notifyLabel(item.notify_state)} ({item.notify_attempts} {item.notify_attempts === 1 ? "attempt" : "attempts"})</dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-2">
        {canDecide(item) && (
          <>
            <button type="button" className={TOUCH_BTN} disabled={disabled} onClick={(e) => h.onDecide(item, "approve", e.currentTarget)} data-testid={`access-${item.id}-approve`}>
              Approve
            </button>
            <button type="button" className={TOUCH_BTN} disabled={disabled} onClick={(e) => h.onDecide(item, "reject", e.currentTarget)} data-testid={`access-${item.id}-reject`}>
              Reject
            </button>
          </>
        )}
        {canResendNotification(item) && (
          <button type="button" className={TOUCH_BTN} disabled={disabled} onClick={() => h.onResend(item, "notification")} data-testid={`access-${item.id}-resend-notification`}>
            Resend notification
          </button>
        )}
        {canResendActivation(item) && (
          <button type="button" className={TOUCH_BTN} disabled={disabled} onClick={() => h.onResend(item, "activation")} data-testid={`access-${item.id}-resend-activation`}>
            Resend activation
          </button>
        )}
        <button type="button" className={TOUCH_BTN} aria-expanded={open} onClick={() => setOpen((v) => !v)} data-testid={`access-${item.id}-toggle`}>
          {open ? "Hide details" : "Show details"}
        </button>
      </div>
      {open && <Detail id={item.id} />}
    </li>
  );
}

function RequestsPage({ filter, beforeId, first, h }: { filter: AccessFilter; beforeId: string | number | null; first: boolean; h: Handlers }) {
  const [more, setMore] = useState(false);
  const { state, refetch } = useAccessRequests(accessQuery(filter, beforeId));
  const emptyText = !first ? "No more requests." : filter === "all" ? "There are no access requests." : `No ${filterLabel(filter).toLowerCase()} requests.`;
  return (
    <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading access requests…", empty: emptyText }}>
      {(data) => (
        <>
          <ul className="grid grid-cols-1 gap-3" data-testid="access-list">
            {data.items.map((item) => (
              <RequestCard key={item.id} item={item} h={h} />
            ))}
          </ul>
          {data.next_before_id !== null && !more && (
            <button type="button" className={TOUCH_BTN} onClick={() => setMore(true)} data-testid="access-more">
              Load more
            </button>
          )}
          {data.next_before_id !== null && more && <RequestsPage filter={filter} beforeId={data.next_before_id} first={false} h={h} />}
        </>
      )}
    </StateBoundary>
  );
}

export function AccessPanel() {
  const { decide, resendNotification, resendActivation } = useAccessActions();
  const [filter, setFilter] = useState<AccessFilter>("pending");
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ item: AccessRequest; decision: AccessDecision } | null>(null);
  const [noteText, setNoteText] = useState("");
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const inFlight = useRef(false);
  const trigger = useRef<HTMLElement | null>(null);
  const noticeRef = useRef<HTMLDivElement | null>(null);

  const openDialog = (item: AccessRequest, decision: AccessDecision, el: HTMLElement) => {
    trigger.current = el;
    setNoteText("");
    setDialogError(null);
    setDialog({ item, decision });
  };

  const confirm = async () => {
    if (!dialog || inFlight.current) return;
    const note = parseNote(noteText);
    if ("error" in note) {
      setDialogError(note.error);
      return;
    }
    inFlight.current = true;
    setDeciding(true);
    setDialogError(null);
    try {
      await decide(dialog.item.id, dialog.decision, note.value);
      setNotice(
        dialog.decision === "approve"
          ? `Approved ${dialog.item.ref}. The activation email is sent in the background; its status shows on the request.`
          : `Rejected ${dialog.item.ref}.`,
      );
      setProblem(null);
      setDialog(null);
    } catch (e) {
      setDialogError(accessErrorText(e, dialog.decision === "approve" ? "approve this request" : "reject this request"));
    } finally {
      inFlight.current = false;
      setDeciding(false);
    }
  };

  const resend = async (item: AccessRequest, kind: "notification" | "activation") => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusyKey(`${item.id}:${kind}`);
    setNotice(null);
    setProblem(null);
    try {
      await (kind === "notification" ? resendNotification(item.id) : resendActivation(item.id));
      setNotice(kind === "notification" ? `Notification email queued for ${item.ref}.` : `A new activation link is being sent for ${item.ref}.`);
    } catch (e) {
      setProblem(accessErrorText(e, kind === "notification" ? "resend the notification" : "resend the activation email"));
    } finally {
      inFlight.current = false;
      setBusyKey(null);
    }
  };

  const handlers: Handlers = { onDecide: openDialog, onResend: (i, k) => void resend(i, k), busyKey };
  const approve = dialog?.decision === "approve";

  return (
    <section aria-labelledby="ad-access" className={SECTION} data-testid="access-panel">
      <h2 id="ad-access" className="text-sm font-semibold text-foreground">Access requests</h2>
      <p className="text-xs text-muted-foreground">
        People who asked for viewer access. Approving sends them a one-time activation link; rejecting does not create an account. Notes are visible to admins only.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="access-filter" className="text-xs text-foreground">Show</label>
        <select id="access-filter" className={`${FIELD} min-h-11`} value={filter} onChange={(e) => setFilter(e.target.value as AccessFilter)} data-testid="access-filter">
          {FILTERS.map((f) => (
            <option key={f} value={f}>{filterLabel(f)}</option>
          ))}
        </select>
      </div>
      <div ref={noticeRef} tabIndex={-1} className="text-xs focus:outline-none" data-testid="access-notices">
        {notice && <p role="status" className="text-foreground" data-testid="access-notice">{notice}</p>}
        {problem && <p role="alert" className="text-destructive-text" data-testid="access-problem">{problem}</p>}
      </div>
      <RequestsPage key={filter} filter={filter} beforeId={null} first h={handlers} />

      <AlertDialog open={dialog !== null} onOpenChange={(o) => { if (!o && !inFlight.current) setDialog(null); }}>
        <AlertDialogContent
          data-testid="access-dialog"
          onCloseAutoFocus={(e) => {
            // Back to the button that opened it; if that row left the list (it was just decided), to the notices region.
            e.preventDefault();
            const el = trigger.current;
            (el && el.isConnected ? el : noticeRef.current)?.focus();
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>{approve ? "Approve this request?" : "Reject this request?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {dialog ? `${dialog.item.name} (${dialog.item.email}, reference ${dialog.item.ref}). ` : ""}
              {approve ? "An activation email is sent to this address and the link works once." : "No account is created."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1">
            <label htmlFor="access-note" className="text-xs font-medium text-foreground">Note (optional, admins only, up to {NOTE_MAX_CHARS} characters)</label>
            <textarea
              id="access-note"
              className={`${FIELD} min-h-[5rem] w-full`}
              value={noteText}
              maxLength={NOTE_MAX_CHARS}
              onChange={(e) => setNoteText(e.target.value)}
              disabled={deciding}
            />
          </div>
          {dialogError && <p role="alert" className="text-sm text-destructive-text" data-testid="access-dialog-error">{dialogError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel className={TOUCH_BTN} disabled={deciding}>Cancel</AlertDialogCancel>
            <button type="button" className={TOUCH_BTN} disabled={deciding} onClick={() => void confirm()} data-testid="access-confirm">
              {deciding ? "Working…" : approve ? "Approve" : "Reject"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
