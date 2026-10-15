import { useApiQuery } from "@/state/useApiQuery";
import { usePageVisible } from "@/components/alerts/usePageVisible";
import { alertsInboxKey, fetchInbox } from "./api";
import type { InboxAlert } from "./model";

export const INBOX_REFRESH_MS = 15_000;

/** The inbox, refreshed every 15 s while the tab is visible. Every component that needs alerts shares this one cached query. */
export function useInbox() {
  const visible = usePageVisible();
  return useApiQuery<InboxAlert[]>({
    queryKey: alertsInboxKey,
    queryFn: ({ signal }) => fetchInbox(signal),
    staleTime: 10_000,
    refetchInterval: visible ? INBOX_REFRESH_MS : false,
    refetchIntervalInBackground: false,
    isEmpty: (rows) => rows.length === 0,
  });
}
