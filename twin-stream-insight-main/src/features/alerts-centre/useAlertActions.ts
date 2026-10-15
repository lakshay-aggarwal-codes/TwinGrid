import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { alertsInboxKey, patchAlert, timelineKey } from "./api";
import type { AlertPatch, InboxAlert } from "./model";

/**
 * `apply(id, patch)` sends the change and, on success, puts the SERVER's row into the shared inbox cache (no optimistic
 * guess) and refreshes that alert's timeline. A failure is thrown to the caller, which shows `changeErrorText(e)`.
 */
export function useAlertActions() {
  const client = useQueryClient();
  return useCallback(
    async (id: number, patch: AlertPatch): Promise<InboxAlert> => {
      const row = await patchAlert(id, patch);
      client.setQueryData<InboxAlert[]>(alertsInboxKey, (old) => (old ? old.map((a) => (a.id === row.id ? row : a)) : old));
      void client.invalidateQueries({ queryKey: timelineKey(id) });
      return row;
    },
    [client],
  );
}
