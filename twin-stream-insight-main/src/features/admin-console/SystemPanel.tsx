import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { API_BASE_URL } from "@/config";
import { StateBoundary } from "@/state/StateBoundary";
import { checkHealthy, checkWord, componentHealthy, componentWord, docsHref, timeText, uptimeText } from "./model";
import { BTN, SECTION, TD, TH } from "./shared";
import { useSystem } from "./useAdmin";

/** A state shown as glyph + word (colour never carries it alone). */
function Mark({ healthy, word }: { healthy: boolean; word: string }) {
  const Icon = healthy ? CheckCircle2 : AlertTriangle;
  return (
    <span className="inline-flex items-center gap-1" data-healthy={healthy}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {word}
    </span>
  );
}

export function SystemPanel() {
  const { state, refetch } = useSystem();
  return (
    <section aria-labelledby="ad-system" className={SECTION} data-testid="system-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ad-system" className="text-sm font-semibold text-foreground">System status</h2>
        <button type="button" className={BTN} onClick={refetch}>Refresh</button>
      </div>
      <StateBoundary state={state} onRetry={refetch} messages={{ loading: "Loading system status…" }}>
        {(s) => (
          <div className="space-y-4">
            {s.unavailable.length > 0 && (
              <p role="status" className="text-xs text-foreground" data-testid="system-unavailable">
                Not available right now: {s.unavailable.join(", ")}.
              </p>
            )}

            <div className="space-y-1" data-testid="system-readiness">
              <h3 className="text-xs font-semibold text-foreground">Readiness</h3>
              {s.readiness ? (
                <>
                  <p className="text-xs text-foreground" data-testid="system-ready-status">
                    <Mark healthy={s.readiness.status === "ready"} word={s.readiness.status === "ready" ? "Ready" : "Not ready"} />
                  </p>
                  <ul className="grid grid-cols-1 gap-x-6 gap-y-0.5 text-xs sm:grid-cols-2">
                    {Object.entries(s.readiness.checks).map(([name, v]) => (
                      <li key={name} className="flex justify-between gap-2" data-testid={`check-${name}`}>
                        <span className="text-muted-foreground">{name}</span>
                        <Mark healthy={checkHealthy(v)} word={checkWord(v)} />
                      </li>
                    ))}
                    {Object.entries(s.readiness.components).map(([name, v]) => (
                      <li key={name} className="flex justify-between gap-2" data-testid={`component-${name}`}>
                        <span className="text-muted-foreground">{name}</span>
                        <Mark healthy={componentHealthy(v)} word={componentWord(v)} />
                      </li>
                    ))}
                  </ul>
                  {s.readiness.degraded.length > 0 && (
                    <p className="text-xs text-muted-foreground">Degraded (does not fail readiness): {s.readiness.degraded.join(", ")}.</p>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">NOT MEASURED: readiness could not be read.</p>
              )}
            </div>

            <div className="space-y-1" data-testid="system-migration">
              <h3 className="text-xs font-semibold text-foreground">Database migration</h3>
              {s.migration ? (
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs">
                  <dt className="text-muted-foreground">Head</dt>
                  <dd className="font-mono">{s.migration.head ?? "unknown"}</dd>
                  <dt className="text-muted-foreground">Database</dt>
                  <dd className="font-mono">{s.migration.database ?? "none recorded"}</dd>
                  <dt className="text-muted-foreground">Status</dt>
                  <dd><Mark healthy={s.migration.at_head} word={s.migration.at_head ? "At head" : "Not at head"} /></dd>
                </dl>
              ) : (
                <p className="text-xs text-muted-foreground">NOT MEASURED: the migration state could not be read.</p>
              )}
            </div>

            <div className="space-y-1" data-testid="system-versions">
              <h3 className="text-xs font-semibold text-foreground">Versions and uptime</h3>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs">
                <dt className="text-muted-foreground">API</dt>
                <dd>{s.versions.title} {s.versions.app}</dd>
                <dt className="text-muted-foreground">Physics version</dt>
                <dd className="font-mono">{s.versions.physics ?? "unknown"}</dd>
                <dt className="text-muted-foreground">Safety envelope</dt>
                <dd className="font-mono">{s.versions.safety_envelope}</dd>
                <dt className="text-muted-foreground">Python</dt>
                <dd className="font-mono">{s.versions.python}</dd>
                <dt className="text-muted-foreground">Uptime</dt>
                <dd data-testid="system-uptime">{uptimeText(s.uptime.seconds)} (since {timeText(s.uptime.started_at)}; {s.uptime.basis})</dd>
              </dl>
            </div>

            <div className="space-y-1" data-testid="system-models">
              <h3 className="text-xs font-semibold text-foreground">Models</h3>
              {s.models.registry === null ? (
                <p className="text-xs text-muted-foreground">NOT MEASURED: the model registry could not be read.</p>
              ) : s.models.registry.length === 0 ? (
                <p className="text-xs text-muted-foreground">The model registry has no entries.</p>
              ) : (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full min-w-[30rem] border-collapse text-sm">
                    <caption className="sr-only">Registered models</caption>
                    <thead className="border-b border-border bg-muted/40">
                      <tr>
                        <th scope="col" className={TH}>Name</th>
                        <th scope="col" className={TH}>Kind</th>
                        <th scope="col" className={TH}>Version</th>
                        <th scope="col" className={TH}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.models.registry.map((m, i) => (
                        <tr key={`${m.name}-${i}`} className="border-b border-border/60 last:border-0">
                          <td className={`${TD} font-mono`}>{m.name ?? "—"}</td>
                          <td className={TD}>{m.kind ?? "—"}</td>
                          <td className={TD}>{m.version ?? "—"}</td>
                          <td className={TD}>{m.status ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="space-y-1" data-testid="system-docs">
              <h3 className="text-xs font-semibold text-foreground">API documentation</h3>
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {(
                  [
                    ["Swagger UI", s.docs.swagger],
                    ["ReDoc", s.docs.redoc],
                    ["OpenAPI JSON", s.docs.openapi],
                  ] as const
                ).map(([label, path]) => (
                  <li key={path}>
                    <a className="text-primary underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={docsHref(API_BASE_URL, path)} target="_blank" rel="noopener noreferrer">
                      {label}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </StateBoundary>
    </section>
  );
}
