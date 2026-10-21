import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createFeatureRegistry } from "../registry";
import feature from "./index";
import { ArchitectureDiagram } from "./ArchitectureDiagram";
import EvidencePage from "./EvidencePage";
import { GENERATED, NOT_RECORDED, highestReward, type EvidenceData } from "./data";

afterEach(cleanup);

const EMPTY: EvidenceData = {
  claims: [],
  limitations: { source: NOT_RECORDED, model_status: [], sections: [] },
  ppo: { outcome: NOT_RECORDED, claim_allowed: NOT_RECORDED, reason: NOT_RECORDED, runs: [], policies: [], policies_source: NOT_RECORDED },
  status: { recorded: false, note: "not recorded for this build", checks: [] },
  skills: [],
};

const FIXTURE: EvidenceData = {
  claims: [
    { id: "C-01", kind: "fact", text: "A simulated twin.", evidence_paths: ["a.md", "b/c.py"], limit: "Not a real facility." },
    { id: "C-02", kind: "result", text: "A number from a run.", evidence_paths: ["r.json"], limit: "One run." },
    { id: "C-03", kind: "assumption", text: "Carbon is assumed.", evidence_paths: ["d.md"], limit: "Flat value." },
    { id: "C-04", kind: "hypothesis", text: "Nobody has measured it.", evidence_paths: ["s.md"], limit: "Not measured." },
    { id: "C-05", kind: "future", text: "Not built.", evidence_paths: ["t.md"], limit: "Needs hardware." },
  ],
  limitations: {
    source: "docs/model_cards/LIMITATIONS.md",
    model_status: [{ model: "Forecaster", statement: "One run, no baseline." }],
    sections: [{ id: "1", title: "Synthetic data", items: [{ title: "Point.", text: "Detail." }] }],
  },
  ppo: {
    outcome: "C",
    claim_allowed: "none",
    reason: "A simpler controller is within tolerance.",
    policies_source: "reports/x/results.json",
    runs: [
      {
        source_path: "reports/x/results.json",
        outcome: "C",
        claim_allowed: "none",
        reason: "r",
        selected_seed: 2,
        physics_version_executed: "1",
        carbon_is_real: false,
        preregistration_sha256: "ab",
        scenario_set_id: "id",
        n_test_scenarios: 60,
        best_constant: "constant[22.75C,closed_loop]",
        generated_at_utc: "2026-10-19T00:00:00+00:00",
      },
    ],
    policies: [
      { policy: "best_constant", total_reward: -36.33, energy_kwh: 9414.4, water_L: 451.5, mean_pue: 1.2091 },
      { policy: "ppo_seed_0", total_reward: -56.24, energy_kwh: 9764.3, water_L: 4871.7, mean_pue: 1.2537 },
    ],
  },
  status: {
    recorded: true,
    recorded_at: "2026-10-21",
    commit: "abc1234",
    checks: [
      { name: "Backend tests", result: "pass", counts: "10 passed", command: "pytest" },
      { name: "Typecheck", result: "fail", counts: "2 errors", command: "npm run typecheck" },
      { name: "Postgres suite", result: "not-run" },
    ],
  },
  skills: [{ id: "security", title: "Security engineering", files: [{ path: "api/auth.py", what: "Tokens" }] }],
};

const show = (data?: EvidenceData) =>
  render(
    <MemoryRouter>
      <EvidencePage data={data} />
    </MemoryRouter>,
  );

describe("EvidencePage with the generated data", () => {
  it("has the heading and the six sections", () => {
    show();
    expect(screen.getByRole("heading", { level: 1, name: "Evidence" })).toBeInTheDocument();
    for (const id of ["scope", "claims", "models", "architecture", "verification", "skills"]) {
      expect(screen.getByTestId(`section-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByRole("navigation", { name: "On this page" })).toBeInTheDocument();
  });

  it("lists every ledger row with its id, its limit and every source path", () => {
    show();
    const ledger = screen.getByTestId("claims-ledger");
    expect(within(ledger).getAllByRole("listitem")).toHaveLength(GENERATED.claims.length);
    for (const c of GENERATED.claims) {
      const row = within(ledger).getByTestId(`claim-${c.id}`);
      expect(row).toHaveTextContent(c.limit.slice(0, 40));
      for (const p of c.evidence_paths) expect(row).toHaveTextContent(p);
    }
  });

  it("shows the registered PPO outcome from the data, with no energy-saving claim", () => {
    show();
    const card = screen.getByTestId("ppo-card");
    expect(screen.getByTestId("ppo-outcome")).toHaveTextContent(`Outcome ${GENERATED.ppo.outcome}`);
    expect(screen.getByTestId("ppo-outcome")).toHaveTextContent(`Claim allowed: ${GENERATED.ppo.claim_allowed}`);
    if (GENERATED.ppo.claim_allowed === "none") expect(card).toHaveTextContent("No energy-saving claim is made.");
    const top = highestReward(GENERATED.ppo.policies);
    if (top) expect(card).toHaveTextContent(`Highest reward here: ${top.policy}`);
    expect(within(screen.getByTestId("ppo-policies")).getAllByRole("row")).toHaveLength(GENERATED.ppo.policies.length + 1);
  });

  it("makes no network request: it is static", () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    const xhr = vi.spyOn(XMLHttpRequest.prototype, "open");
    show();
    expect(f).not.toHaveBeenCalled();
    expect(xhr).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
    xhr.mockRestore();
  });
});

describe("EvidencePage with fixtures", () => {
  it("filters the ledger by status and says how many are shown", () => {
    show(FIXTURE);
    expect(screen.getByTestId("claims-count")).toHaveTextContent("Showing 5 of 5 claims.");
    fireEvent.click(screen.getByRole("button", { name: /^Not supported/ }));
    expect(screen.getByTestId("claims-count")).toHaveTextContent("Showing 2 of 5 claims.");
    expect(screen.queryByTestId("claim-C-01")).toBeNull();
    expect(screen.getByTestId("claim-C-04")).toHaveAttribute("data-group", "not-supported");
    expect(screen.getByTestId("claim-C-05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Supported/ }));
    expect(screen.getAllByTestId(/^claim-C-/).map((e) => e.getAttribute("data-testid"))).toEqual(["claim-C-01", "claim-C-02"]);
    fireEvent.click(screen.getByRole("button", { name: /^Assumption/ }));
    expect(screen.getAllByTestId(/^claim-C-/)).toHaveLength(1);
    expect(screen.getByRole("button", { name: /^Assumption/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("states a claim's status in words, not by colour alone", () => {
    show(FIXTURE);
    expect(screen.getByTestId("claim-C-04")).toHaveTextContent("Not supported (hypothesis)");
    expect(screen.getByTestId("claim-C-01")).toHaveTextContent("Supported (fact)");
  });

  it("shows the PPO outcome C as the registered negative result", () => {
    show(FIXTURE);
    expect(screen.getByTestId("ppo-outcome")).toHaveTextContent("Outcome C (replace with a simpler controller). Claim allowed: none. No energy-saving claim is made.");
    expect(screen.getByTestId("ppo-card")).toHaveTextContent("Highest reward here: best_constant (-36.33)");
    expect(screen.getByTestId("ppo-card")).toHaveTextContent("reports/x/results.json");
  });

  it("shows a recorded verification table with a word and a glyph for each result", () => {
    show(FIXTURE);
    const rows = within(screen.getByTestId("status-checks")).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveAttribute("data-result", "pass");
    expect(rows[2]).toHaveTextContent("fail");
    expect(rows[3]).toHaveTextContent("not run");
    expect(rows[3]).toHaveTextContent(NOT_RECORDED); // no counts, no command given
    expect(screen.queryByTestId("status-not-recorded")).toBeNull();
  });

  it("with every source missing, says 'not recorded' and invents nothing", () => {
    show(EMPTY);
    expect(screen.getAllByTestId("not-recorded").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByTestId("status-not-recorded")).toHaveTextContent("Not recorded for this build");
    expect(screen.queryByTestId("ppo-card")).toBeNull();
    expect(screen.queryByTestId("claims-ledger")).toBeNull();
    expect(screen.queryByText(/Outcome C/)).toBeNull();
    expect(screen.queryByText(/\bpass\b/i)).toBeNull();
    // the static sections still render
    expect(screen.getByTestId("architecture")).toBeInTheDocument();
    expect(screen.getByTestId("section-scope")).toBeInTheDocument();
  });
});

describe("architecture diagram", () => {
  it("is an image with a title and has a text equivalent that includes what is not built", () => {
    render(<ArchitectureDiagram />);
    expect(screen.getByRole("img", { name: /architecture boundaries/i })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "What each box is" });
    expect(list).toHaveTextContent("Real facility");
    expect(list).toHaveTextContent("Not connected");
    expect(list).toHaveTextContent("Postgres");
  });
});

describe("feature module", () => {
  it("registers /evidence under the Evidence nav group for every signed-in role", () => {
    const r = createFeatureRegistry([feature], { onReject: () => undefined });
    expect(r.rejected).toEqual([]);
    expect(r.allRoutes().map((x) => [x.path, x.minRole])).toEqual([["/evidence", "viewer"]]);
    expect(r.navGroups("viewer").map((g) => [g.group, g.items.map((i) => i.label)])).toEqual([["Evidence", ["Evidence"]]]);
  });
});

// ---- the honesty test ------------------------------------------------------------------------------------------------

/** Words this project does not use about itself (see docs/CLAIMS.md). Built here, in a test file, on purpose. */
const BANNED: readonly RegExp[] = [/calibrated/gi, /saves energy/gi, /production[- ]ready/gi, /ai[- ]optimi[sz]ed/gi, /state[- ]of[- ]the[- ]art/gi, /wcag[- ]compliant/gi, /penetration[- ]tested/gi];

/** True when a banned word is used in order to deny it ("not calibrated", "uncalibrated", "no claim ... saves energy"). */
function isNegated(text: string, index: number): boolean {
  const before = text.slice(0, index).toLowerCase();
  if (before.endsWith("un")) return true;
  return /\b(not|no|never|nothing|without|isn't|cannot|n't)\b/.test(before.slice(-48));
}

function occurrences(text: string): { word: string; index: number }[] {
  const out: { word: string; index: number }[] = [];
  for (const re of BANNED) for (const m of text.matchAll(re)) out.push({ word: m[0], index: m.index ?? 0 });
  return out;
}

describe("honesty", () => {
  it("the checker itself: flags a positive use, accepts a denial", () => {
    const bad = "The platform is production-ready and saves energy.";
    expect(occurrences(bad).filter((o) => !isNegated(bad, o.index))).toHaveLength(2);
    const ok = "Not calibrated to any facility. The physics is uncalibrated. No claim is made that it saves energy.";
    expect(occurrences(ok).filter((o) => !isNegated(ok, o.index))).toEqual([]);
  });

  it("the page's own wording contains none of the banned words (generated source text excluded)", () => {
    const { container } = show();
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('[data-quoted="source"]').forEach((n) => n.remove());
    expect(occurrences(clone.textContent ?? "")).toEqual([]);
  });

  it("a banned word appears in quoted source text only as a denial, or in a row that is not marked supported", () => {
    const { container } = show();
    const offending: string[] = [];
    container.querySelectorAll('[data-quoted="source"]').forEach((zone) => {
      const rows = zone.querySelectorAll("[data-group]");
      const scan = (el: Element) => {
        const text = el.textContent ?? "";
        const notSupported = el.getAttribute("data-group") !== null && el.getAttribute("data-group") !== "supported";
        for (const o of occurrences(text)) if (!isNegated(text, o.index) && !notSupported) offending.push(`${o.word} in ${el.getAttribute("data-testid") ?? zone.getAttribute("data-testid")}`);
      };
      if (rows.length > 0) rows.forEach(scan);
      else scan(zone);
    });
    expect(offending).toEqual([]);
  });

  it("the feature's source files contain none of the banned words", () => {
    const dir = __dirname;
    const files = readdirSync(dir).filter((f) => /\.tsx?$/.test(f) && !/\.test\./.test(f));
    expect(files).toContain("EvidencePage.tsx");
    for (const f of files) {
      const text = readFileSync(join(dir, f), "utf8");
      expect(occurrences(text), f).toEqual([]);
    }
  });
});
