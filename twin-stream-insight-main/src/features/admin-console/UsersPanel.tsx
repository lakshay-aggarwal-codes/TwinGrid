import { useState } from "react";
import { StateBoundary } from "@/state/StateBoundary";
import { actionErrorText } from "./errors";
import { ROLES, ROLE_LABEL, canSetRole, timeText } from "./model";
import { BTN, FIELD, SECTION, TD, TH } from "./shared";
import type { User } from "./schema";
import { useUserActions, useUsers } from "./useAdmin";

function UserRow({ u }: { u: User }) {
  const { setRole } = useUserActions();
  const [choice, setChoice] = useState(u.role);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const apply = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const row = await setRole(u.id, choice);
      setDone(`Role set to ${ROLE_LABEL[row.role] ?? row.role}.`);
    } catch (e) {
      setError(actionErrorText(e, "change this role"));
      setChoice(u.role);
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr className="border-b border-border/60 last:border-0" data-testid={`user-${u.id}`}>
      <th scope="row" className="px-2 py-1.5 text-left text-xs font-medium text-foreground">
        {u.username}
        {u.is_you && <span className="ml-2 rounded border border-border px-1 text-[10px] font-normal text-muted-foreground">You</span>}
      </th>
      <td className={TD} data-testid={`user-${u.id}-role`}>{ROLE_LABEL[u.role] ?? `${u.role} (unrecognised)`}</td>
      <td className={TD}>{timeText(u.created_at)}</td>
      <td className={TD}>
        {u.is_you ? (
          <span className="text-muted-foreground">You cannot change your own role.</span>
        ) : (
          <span className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.username}</label>
            <select id={`role-${u.id}`} className={FIELD} value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
              {ROLES.map((r) => (
                <option key={r} value={r}>{ROLE_LABEL[r]}</option>
              ))}
            </select>
            <button type="button" className={BTN} disabled={busy || !canSetRole(u, choice)} onClick={() => void apply()} data-testid={`user-${u.id}-apply`}>
              Set role
            </button>
          </span>
        )}
        {done && <span role="status" className="mt-1 block text-muted-foreground" data-testid={`user-${u.id}-done`}>{done}</span>}
        {error && <span role="alert" className="mt-1 block text-destructive-text" data-testid={`user-${u.id}-error`}>{error}</span>}
      </td>
    </tr>
  );
}

export function UsersPanel() {
  const { state, refetch } = useUsers();
  return (
    <section aria-labelledby="ad-users" className={SECTION} data-testid="users-panel">
      <h2 id="ad-users" className="text-sm font-semibold text-foreground">Users and roles</h2>
      <p className="text-xs text-muted-foreground">
        A role change applies on the user's next request. You cannot change your own role. Accounts are created through sign-up or the seed script, not here.
      </p>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading users…", empty: "There are no users." }}>
        {(data) => (
          <>
            <p className="text-xs text-foreground" data-testid="user-counts">
              {data.roles.map((r) => `${ROLE_LABEL[r] ?? r}: ${data.counts[r] ?? 0}`).join(" · ")}
              {data.truncated && " · list truncated"}
            </p>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full min-w-[32rem] border-collapse text-sm">
                <caption className="sr-only">Users and their roles</caption>
                <thead className="border-b border-border bg-muted/40">
                  <tr>
                    <th scope="col" className={TH}>User</th>
                    <th scope="col" className={TH}>Role</th>
                    <th scope="col" className={TH}>Created</th>
                    <th scope="col" className={TH}>Change role</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <UserRow key={u.id} u={u} />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </StateBoundary>
    </section>
  );
}
