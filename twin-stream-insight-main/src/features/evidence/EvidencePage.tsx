import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "@/hooks/usePageTitle";
import { ArchitectureDiagram } from "./ArchitectureDiagram";
import {
  CLAIM_FILTERS,
  GENERATED,
  MODEL_CLAIM_IDS,
  NOT_RECORDED,
  SOURCES,
  claimById,
  claimGroup,
  countClaims,
  filterClaims,
  fmt,
  highestReward,
  type CheckResult,
  type Claim,
  type ClaimFilter,
  type EvidenceData,
  type PpoResult,
  type VerificationStatus,
} from "./data";

const SECTIONS = [
  { id: "scope", label: "What this is and isn't" },
  { id: "claims", label: "Claims ledger" },
  { id: "models", label: "Model status" },
  { id: "architecture", label: "Architecture" },
  { id: "verification", label: "How it was verified" },
  { id: "skills", label: "Skills map" },
] as const;

/** Where a figure came from. Every figure on this page has one. */
function Source({ children }: { children: string }) {
  return (
    <p className="text-[11px] text-muted-foreground">
      Source: <code className="break-all">{children}</code>
    </p>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`ev-${id}`} className="scroll-mt-4 space-y-3" data-testid={`section-${id}`}>
      <h2 id={`ev-${id}`} className="text-base font-semibold text-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function NotRecorded({ what }: { what: string }) {
  return (
    <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground" data-testid="not-recorded">
      {what}: {NOT_RECORDED}.
    </p>
  );
}

// ---- 1. scope ------------------------------------------------------------------------------------------------------

const IS = [
  "A simulation-based data-centre digital-twin platform. Every number it shows comes from its own simulator.",
  "A way to look at simulated telemetry, alerts, what-if runs and model results, with the evidence and the limits next to each.",
];
const IS_NOT = [
  "Not a twin of any real facility. No real measurements are used.",
  "Not connected to any real facility, and it controls no equipment. Approvals are records in a database.",
  "Its physics values are not fitted to any facility's data, and its carbon figure is a flat assumed value.",
  "Not independently security-tested, and not audited against an accessibility standard.",
];

function Scope() {
  return (
    <Section id="scope" title="What this is and isn't">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border border-border bg-card p-3">
          <h3 className="mb-2 text-sm font-medium text-foreground">It is</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {IS.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-border bg-card p-3">
          <h3 className="mb-2 text-sm font-medium text-foreground">It is not</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {IS_NOT.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      </div>
      <Source>{`${SOURCES.claims} (rows C-01 to C-04, C-21, C-22, C-30)`}</Source>
    </Section>
  );
}

// ---- 2. claims ledger -----------------------------------------------------------------------------------------------

const KIND_MARK: Record<string, string> = { supported: "●", assumption: "◐", "not-supported": "○" };
const KIND_WORD: Record<string, string> = { supported: "Supported", assumption: "Assumption", "not-supported": "Not supported" };

function ClaimRow({ claim }: { claim: Claim }) {
  const group = claimGroup(claim.kind);
  return (
    <li className="space-y-1.5 rounded-md border border-border bg-card p-3" data-testid={`claim-${claim.id}`} data-kind={claim.kind} data-group={group}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono font-semibold text-foreground">{claim.id}</span>
        <span className="rounded border border-border px-1.5 py-0.5 text-foreground">
          <span aria-hidden="true">{KIND_MARK[group]} </span>
          {KIND_WORD[group]} <span className="text-muted-foreground">({claim.kind})</span>
        </span>
      </div>
      <p className="text-sm text-foreground">{claim.text}</p>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Limit: </span>
        {claim.limit}
      </p>
      <p className="text-[11px] text-muted-foreground">
        Source:{" "}
        {claim.evidence_paths.length === 0
          ? NOT_RECORDED
          : claim.evidence_paths.map((p, i) => (
              <span key={p}>
                {i > 0 && ", "}
                <code className="break-all">{p}</code>
              </span>
            ))}
      </p>
    </li>
  );
}

function ClaimsLedger({ claims }: { claims: Claim[] }) {
  const [filter, setFilter] = useState<ClaimFilter>("all");
  const shown = filterClaims(claims, filter);
  return (
    <Section id="claims" title="Claims ledger">
      <p className="text-sm text-muted-foreground">
        Every public claim about the project is one row, with a status, the files that back it and the limit of what it means. Rows that are assumptions, hypotheses or not built are listed too, and marked.
      </p>
      {claims.length === 0 ? (
        <NotRecorded what="Claims ledger" />
      ) : (
        <>
          <div role="group" aria-label="Filter claims by status" className="flex flex-wrap gap-2">
            {CLAIM_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                title={f.hint}
                onClick={() => setFilter(f.id)}
                className={`rounded-md border px-2.5 py-1 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  filter === f.id ? "border-primary bg-primary/20 text-foreground" : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {f.label} ({countClaims(claims, f.id)})
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground" aria-live="polite" data-testid="claims-count">
            Showing {shown.length} of {claims.length} claims.
          </p>
          <ul className="space-y-2" data-testid="claims-ledger" data-quoted="source" aria-label="Claims">
            {shown.map((c) => (
              <ClaimRow key={c.id} claim={c} />
            ))}
          </ul>
        </>
      )}
      <Source>{SOURCES.claims}</Source>
    </Section>
  );
}

// ---- 3. model status ----------------------------------------------------------------------------------------------

function PpoCard({ ppo }: { ppo: PpoResult }) {
  if (ppo.runs.length === 0) return <NotRecorded what="PPO decision-gate result" />;
  const top = highestReward(ppo.policies);
  const noClaim = ppo.claim_allowed === "none";
  return (
    <div className="space-y-3 rounded-md border border-border bg-card p-3" data-testid="ppo-card">
      <h3 className="text-sm font-medium text-foreground">PPO optimizer: the registered evaluation</h3>
      <p className="text-sm text-foreground" data-testid="ppo-outcome">
        Outcome {ppo.outcome}
        {ppo.outcome === "C" ? " (replace with a simpler controller)" : ""}. Claim allowed: {ppo.claim_allowed}.
        {noClaim ? " No energy-saving claim is made." : ""}
      </p>
      <p className="text-xs text-muted-foreground" data-quoted="source">{ppo.reason}</p>
      <p className="text-xs text-muted-foreground">
        This is a kept negative result. The protocol was registered before the first run (reports/policy_evaluation_physics1/PREREGISTRATION.md), and the outcome is shown as it came out. It is here as an example of evaluation rigor, not as a feature.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-left text-xs" data-testid="ppo-policies">
          <caption className="pb-1 text-left text-muted-foreground">
            Mean per episode on the test scenarios, simulator only. Higher reward is better.
            {top ? ` Highest reward here: ${top.policy} (${fmt(top.total_reward)}).` : ""}
          </caption>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th scope="col" className="py-1 pr-3 font-medium">Policy</th>
              <th scope="col" className="py-1 pr-3 font-medium">Reward</th>
              <th scope="col" className="py-1 pr-3 font-medium">Energy (kWh)</th>
              <th scope="col" className="py-1 pr-3 font-medium">Water (L)</th>
              <th scope="col" className="py-1 font-medium">Mean PUE</th>
            </tr>
          </thead>
          <tbody>
            {ppo.policies.map((p) => (
              <tr key={p.policy} className="border-b border-border/50 text-foreground">
                <th scope="row" className="py-1 pr-3 font-mono font-normal">{p.policy}</th>
                <td className="py-1 pr-3">{fmt(p.total_reward)}</td>
                <td className="py-1 pr-3">{fmt(p.energy_kwh, 0)}</td>
                <td className="py-1 pr-3">{fmt(p.water_L, 0)}</td>
                <td className="py-1">{fmt(p.mean_pue, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Source>{ppo.policies_source}</Source>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] text-left text-xs" data-testid="ppo-runs">
          <caption className="pb-1 text-left text-muted-foreground">Recorded runs of the same registered evaluation.</caption>
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th scope="col" className="py-1 pr-3 font-medium">Run file</th>
              <th scope="col" className="py-1 pr-3 font-medium">Outcome</th>
              <th scope="col" className="py-1 pr-3 font-medium">Claim allowed</th>
              <th scope="col" className="py-1 pr-3 font-medium">Physics</th>
              <th scope="col" className="py-1 font-medium">Carbon</th>
            </tr>
          </thead>
          <tbody>
            {ppo.runs.map((r) => (
              <tr key={r.source_path} className="border-b border-border/50 align-top text-foreground">
                <td className="py-1 pr-3">
                  <code className="break-all">{r.source_path}</code>
                </td>
                <td className="py-1 pr-3">{fmt(r.outcome)}</td>
                <td className="py-1 pr-3">{fmt(r.claim_allowed)}</td>
                <td className="py-1 pr-3">{fmt(r.physics_version_executed)}</td>
                <td className="py-1">{r.carbon_is_real === false ? "assumed (flat)" : r.carbon_is_real === true ? "real curve" : NOT_RECORDED}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ModelStatus({ data }: { data: EvidenceData }) {
  const { limitations, claims, ppo } = data;
  const figures = MODEL_CLAIM_IDS.map((id) => claimById(claims, id)).filter((c): c is Claim => c !== undefined);
  return (
    <Section id="models" title="Model status">
      <p className="text-sm text-muted-foreground">
        All three models are trained on data from the simulator itself, so their numbers describe the simulator, not a real facility.
      </p>
      {limitations.model_status.length === 0 ? (
        <NotRecorded what="Model status" />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2" data-testid="model-status" data-quoted="source">
          {limitations.model_status.map((m) => (
            <li key={m.model} className="rounded-md border border-border bg-card p-3 text-sm">
              <span className="font-medium text-foreground">{m.model}. </span>
              <span className="text-muted-foreground">{m.statement}</span>
            </li>
          ))}
        </ul>
      )}
      <Source>{limitations.source}</Source>

      {figures.length > 0 && (
        <ul className="space-y-2" data-testid="model-figures" data-quoted="source" aria-label="Reported model figures and their limits">
          {figures.map((c) => (
            <li key={c.id} className="rounded-md border border-border bg-card p-3 text-sm">
              <p className="text-foreground">
                <span className="font-mono text-xs">{c.id}</span> {c.text}
              </p>
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Limit: </span>
                {c.limit}
              </p>
            </li>
          ))}
        </ul>
      )}

      <PpoCard ppo={ppo} />

      {limitations.sections.length > 0 && (
        <details className="rounded-md border border-border bg-card p-3" data-testid="shared-limitations" data-quoted="source">
          <summary className="cursor-pointer text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            Limitations that apply to every model
          </summary>
          <div className="mt-3 space-y-3">
            {limitations.sections.map((s) => (
              <div key={s.id}>
                <h3 className="text-sm font-medium text-foreground">{s.title}</h3>
                <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                  {s.items.map((i) => (
                    <li key={`${i.title}${i.text}`}>
                      {i.title && <span className="font-medium text-foreground">{i.title} </span>}
                      {i.text}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}
    </Section>
  );
}

// ---- 4. architecture ----------------------------------------------------------------------------------------------

function Architecture() {
  return (
    <Section id="architecture" title="Architecture">
      <ArchitectureDiagram />
    </Section>
  );
}

// ---- 5. how it was verified ---------------------------------------------------------------------------------------

const RESULT_MARK: Record<CheckResult, { mark: string; word: string }> = {
  pass: { mark: "✓", word: "pass" },
  fail: { mark: "✗", word: "fail" },
  skipped: { mark: "–", word: "skipped" },
  "not-run": { mark: "○", word: "not run" },
};

function Verification({ status }: { status: VerificationStatus }) {
  return (
    <Section id="verification" title="How it was verified">
      {!status.recorded || status.checks.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground" data-testid="status-not-recorded">
          Not recorded for this build. Check results are shown here only when a recorded result is supplied; until then nothing on this page says any check was run or succeeded.
        </p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {status.recorded_at ? `Recorded ${status.recorded_at}. ` : ""}
            {status.commit ? `Commit ${status.commit}. ` : ""}
            {status.note ?? ""}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-xs" data-testid="status-checks">
              <caption className="sr-only">Recorded check results</caption>
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th scope="col" className="py-1 pr-3 font-medium">Check</th>
                  <th scope="col" className="py-1 pr-3 font-medium">Result</th>
                  <th scope="col" className="py-1 pr-3 font-medium">Counts</th>
                  <th scope="col" className="py-1 font-medium">Command</th>
                </tr>
              </thead>
              <tbody>
                {status.checks.map((c) => (
                  <tr key={`${c.name}${c.command ?? ""}`} className="border-b border-border/50 align-top text-foreground" data-result={c.result}>
                    <th scope="row" className="py-1 pr-3 font-normal">{c.name}</th>
                    <td className="py-1 pr-3">
                      <span aria-hidden="true">{RESULT_MARK[c.result]?.mark} </span>
                      {RESULT_MARK[c.result]?.word ?? c.result}
                    </td>
                    <td className="py-1 pr-3">{c.counts ?? NOT_RECORDED}</td>
                    <td className="py-1">{c.command ? <code className="break-all">{c.command}</code> : NOT_RECORDED}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Source>{SOURCES.status}</Source>
    </Section>
  );
}

// ---- 6. skills map -----------------------------------------------------------------------------------------------

function Skills({ skills }: { skills: EvidenceData["skills"] }) {
  return (
    <Section id="skills" title="Skills map">
      <p className="text-sm text-muted-foreground">Where to look in the repository for each kind of work. Every path below exists in this build.</p>
      <div className="grid gap-3 md:grid-cols-2" data-testid="skills">
        {skills.map((a) => (
          <div key={a.id} className="rounded-md border border-border bg-card p-3">
            <h3 className="mb-2 text-sm font-medium text-foreground">{a.title}</h3>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {a.files.map((f) => (
                <li key={f.path}>
                  <code className="break-all text-foreground">{f.path}</code>: {f.what}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---- page ---------------------------------------------------------------------------------------------------------

export default function EvidencePage({ data = GENERATED }: { data?: EvidenceData }) {
  usePageTitle("TwinGrid — Evidence");
  return (
    <main className="mx-auto h-full w-full max-w-6xl space-y-6 overflow-y-auto p-4" data-testid="evidence-page">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">Evidence</h1>
        <Link to="/" className="text-xs text-primary underline">
          Back to live twin
        </Link>
      </header>
      <p className="text-sm text-muted-foreground">
        What the project claims, what backs each claim, and where it stops. It is generated from the repository's own documents and needs no backend. Everything on it is simulated.
      </p>
      <nav aria-label="On this page" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SECTIONS.map((s) => (
          <a key={s.id} href={`#ev-${s.id}`} className="text-primary underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {s.label}
          </a>
        ))}
      </nav>
      <Scope />
      <ClaimsLedger claims={data.claims} />
      <ModelStatus data={data} />
      <Architecture />
      <Verification status={data.status} />
      <Skills skills={data.skills} />
    </main>
  );
}
