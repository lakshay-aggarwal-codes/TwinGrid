import type { UiStateKind } from "@/state/dataState";

/**
 * Plain-language wording for the states people meet most. Each says what is going on and what they can do about it, and
 * none of them shows backend text. Kinds not listed here fall back to the shared `STATE_COPY`.
 */
export const PLAIN_COPY: Partial<Record<UiStateKind, { title: string; description: string }>> = {
  empty: { title: "Nothing here yet", description: "There is nothing to show for this yet." },
  not_run: { title: "Not run yet", description: "This has not been run yet. Start it to see results here." },
  stale: { title: "This may be out of date", description: "The latest update is older than expected. The values shown are the last ones received." },
  disconnected: { title: "Connection lost", description: "The live connection is down. The app reconnects on its own when it can; the values shown are the last ones received." },
  unavailable: { title: "Service unavailable", description: "The backend is not responding right now. Try again in a moment." },
};
