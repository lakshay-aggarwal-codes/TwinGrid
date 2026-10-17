import { useEffect, useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useApiQuery } from "@/state/useApiQuery";
import { StandardBoundary } from "@/features/app-states/StandardState";
import { fetchFleet } from "./api";
import type { Fleet, Site } from "./schema";
import { SORT_OPTIONS, labLink, rankFor, setSite, siteFromSearch, sortSites, useSite, withSite, type SortKey } from "./model";
import { useState } from "react";

const fmt = (n: number, d = 2): string => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const btn = "rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function SiteCard({ site, fleet, sortKey, selected, onSelect }: { site: Site; fleet: Fleet; sortKey: SortKey; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        data-testid={`site-${site.id}`}
        className={`w-full rounded-lg border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? "border-primary bg-muted" : "border-border bg-card hover:bg-muted"}`}
      >
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">{site.name}</span>
          <span className="text-xs text-muted-foreground" data-testid={`rank-${site.id}`}>
            Rank {rankFor(site, sortKey)} of {fleet.sites.length}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">{site.climate}</p>
        <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
          <div>
            <dt className="text-muted-foreground">PUE</dt>
            <dd className="font-medium">{fmt(site.pue)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Carbon</dt>
            <dd className="font-medium">{fmt(site.carbon_gco2_per_step, 0)} g</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Alert conditions</dt>
            <dd className="font-medium">{site.alert_conditions}</dd>
          </div>
        </dl>
        <p className="mt-2 text-[11px] uppercase tracking-wide text-muted-foreground">Simulated</p>
      </button>
    </li>
  );
}

function Detail({ site, fleet }: { site: Site; fleet: Fleet }) {
  return (
    <section aria-label={`${site.name} detail`} data-testid="site-detail" className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold">{site.name} <span className="text-xs font-normal text-muted-foreground">(simulated)</span></h2>
      <p className="text-sm text-muted-foreground">{site.climate}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        <dt className="text-muted-foreground">IT load</dt><dd>{fmt(site.inputs.utilisation * 100, 0)}%</dd>
        <dt className="text-muted-foreground">Outside temperature</dt><dd>{fmt(site.inputs.outside_temp_C, 1)} °C</dd>
        <dt className="text-muted-foreground">Water stress</dt><dd>{fmt(site.inputs.water_stress, 2)}</dd>
        <dt className="text-muted-foreground">Cooling mode</dt><dd>{site.cooling_mode}</dd>
        <dt className="text-muted-foreground">PUE / WUE</dt><dd>{fmt(site.pue)} / {fmt(site.wue)}</dd>
        <dt className="text-muted-foreground">Total power</dt><dd>{fmt(site.total_power_kw, 0)} kW</dd>
        <dt className="text-muted-foreground">Outlet temperature</dt><dd>{fmt(site.server_outlet_temp_C, 1)} °C</dd>
        <dt className="text-muted-foreground">Carbon ({fleet.carbon_unit})</dt><dd>{fmt(site.carbon_gco2_per_step, 0)}</dd>
        <dt className="text-muted-foreground">Alert conditions</dt>
        <dd>{site.alert_conditions === 0 ? "None" : site.alert_condition_names.join(", ")}</dd>
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">{fleet.alert_note}</p>
      <Link to={labLink(site)} className={`${btn} mt-3 inline-block`}>
        Open in the What-if lab
      </Link>
    </section>
  );
}

/** `/fleet`. Every number is the backend's own simulated twin run; this page only sorts, selects and links. */
export default function FleetPage() {
  usePageTitle("TwinGrid — Fleet view");
  const { search } = useLocation();
  const navigate = useNavigate();
  const q = useApiQuery<Fleet>({ queryKey: ["fleet-sites"], queryFn: ({ signal }) => fetchFleet(signal), staleTime: 15_000, retry: false, refetchOnWindowFocus: false, isEmpty: (f) => f.sites.length === 0 });
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const siteId = useSite();
  const data = q.state.status === "ready" ? q.state.data : null;
  const ids = useMemo(() => (data ? data.sites.map((s) => s.id) : []), [data]);

  // The address names the selected site, so a copied link reopens the same one; the store is the site context.
  useEffect(() => {
    if (ids.length > 0) setSite(siteFromSearch(search, ids));
    // `search` is the source here; the effect below writes it back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join("|")]);
  const select = (id: string) => {
    setSite(id);
    navigate({ search: withSite(search, id) }, { replace: true });
  };

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-4">
      <header>
        <h1 className="text-xl font-semibold">Fleet view</h1>
        <p className="text-sm text-muted-foreground">{data?.label ?? "Simulated sites: the digital twin run under five different parameter sets. Not real facilities."}</p>
      </header>
      <StandardBoundary state={q.state} onRetry={q.refetch} skeleton="card">
        {(fleet) => {
          const sorted = sortSites(fleet.sites, sortKey);
          const selected = fleet.sites.find((s) => s.id === siteId) ?? null;
          return (
            <>
              <div role="group" aria-label="Sort sites by" className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">Sort by</span>
                {SORT_OPTIONS.map((o) => (
                  <button key={o.key} type="button" aria-pressed={sortKey === o.key} onClick={() => setSortKey(o.key)} className={`${btn} ${sortKey === o.key ? "bg-muted" : ""}`}>
                    {o.label}
                  </button>
                ))}
                <span className="text-xs text-muted-foreground">Lower is better for all three.</span>
              </div>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Simulated sites">
                {sorted.map((s) => (
                  <SiteCard key={s.id} site={s} fleet={fleet} sortKey={sortKey} selected={s.id === siteId} onSelect={() => select(s.id)} />
                ))}
              </ul>
              <p className="text-xs text-muted-foreground" data-testid="carbon-note">{fleet.carbon_note}</p>
              {selected ? <Detail site={selected} fleet={fleet} /> : <p className="text-sm text-muted-foreground">Select a site to see its detail.</p>}
            </>
          );
        }}
      </StandardBoundary>
    </main>
  );
}
