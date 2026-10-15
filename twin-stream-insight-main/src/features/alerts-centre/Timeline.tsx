import { MessageSquare, Radio, UserRound, Workflow } from "lucide-react";
import { useApiQuery } from "@/state/useApiQuery";
import { StateBoundary } from "@/state/StateBoundary";
import { fetchTimeline, timelineKey } from "./api";
import { formatUtc, type Timeline as TimelineData } from "./model";

const KIND_ICON = { created: Radio, status: Workflow, assigned: UserRound, note: MessageSquare } as const;

/** The incident timeline of one alert, oldest first. Every entry is a sentence plus the time (UTC) and who did it. */
export function Timeline({ alertId }: { alertId: number }) {
  const { state, refetch } = useApiQuery<TimelineData>({
    queryKey: timelineKey(alertId),
    queryFn: ({ signal }) => fetchTimeline(alertId, signal),
    staleTime: 5_000,
  });
  return (
    <section aria-label="Incident timeline" data-testid="timeline">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Incident timeline</h3>
      <StateBoundary state={state} onRetry={refetch} block={false}>
        {(data) => (
          <ol className="space-y-2 border-l border-border pl-3">
            {data.entries.map((e, i) => {
              const Icon = KIND_ICON[e.kind as keyof typeof KIND_ICON] ?? Workflow;
              return (
                <li key={`${e.at ?? "?"}-${i}`} className="text-sm">
                  <span className="flex items-start gap-1.5">
                    <Icon aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0">
                      <span className="break-words">{e.summary}</span>
                      {e.actor ? <span className="text-muted-foreground"> by {e.actor}</span> : null}
                      <span className="block text-[11px] text-muted-foreground">{formatUtc(e.at)}</span>
                      {e.note ? <span className="mt-0.5 block whitespace-pre-wrap break-words rounded bg-muted/60 px-2 py-1 text-xs">{e.note}</span> : null}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </StateBoundary>
    </section>
  );
}
