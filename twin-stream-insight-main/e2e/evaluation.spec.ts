import { test, expect } from "@playwright/test";
import { signIn } from "./helpers";

/**
 * E2E-2, evaluation half (FE-17, gate G-EVAL): real backend + seeded viewer, no interception.
 * login -> open the evaluation view -> the screen must agree with what the backend REALLY answered from
 * GET /api/evaluations/{id}: outcome code, claim text, policy rows in backend order, evaluation scenario-set id,
 * pre-registration hash, simulator-only provenance, and the backend-defined outcome text (or "definition not provided").
 * The run half of E2E-2 (submit a run, observe real run states) belongs to the FE-16 run flow and is not part of this spec.
 */
test("E2E-2 (evaluation): backend evaluation report is displayed as the backend defined it", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, "viewer");

  const isPath = (url: string, re: RegExp) => re.test(new URL(url).pathname);
  const listResponse = page.waitForResponse((r) => isPath(r.url(), /\/api\/evaluations$/) && r.request().method() === "GET", { timeout: 60_000 });
  const detailResponse = page.waitForResponse((r) => isPath(r.url(), /\/api\/evaluations\/[^/]+$/) && r.request().method() === "GET", { timeout: 60_000 });

  // Client-side navigation: the session lives in memory, so the page is not reloaded.
  await page.evaluate(() => {
    window.history.pushState({}, "", "/evaluation");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });

  expect((await listResponse).status()).toBe(200);
  const detail = await detailResponse;
  expect(detail.status()).toBe(200);
  const body = (await detail.json()) as {
    evaluation_id: string;
    origin?: string;
    scenario_set_id?: string;
    preregistration_sha256?: string;
    outcome_definitions?: Record<string, string>;
    decision: { outcome: string; claim_allowed: string; reason?: string };
    policies: { policy_id: string }[];
  };

  const view = page.getByTestId("evaluation-view");
  await expect(view).toBeVisible({ timeout: 30_000 });
  await expect(view).toHaveAttribute("data-evaluation-id", body.evaluation_id);

  // Outcome and claim: the backend's words, verbatim.
  const banner = page.getByLabel("Evaluation outcome");
  await expect(banner).toHaveAttribute("data-outcome-code", body.decision.outcome);
  await expect(page.getByTestId("outcome-claim")).toContainText(body.decision.claim_allowed);
  if (body.decision.reason) await expect(page.getByTestId("outcome-reason")).toContainText(body.decision.reason);

  // Backend-defined outcome text, or the explicit "definition not provided".
  const definition = body.outcome_definitions?.[body.decision.outcome];
  if (definition) await expect(page.getByTestId("outcome-definition")).toContainText(definition);
  else await expect(page.getByTestId("outcome-definition")).toContainText("definition not provided");
  if (body.decision.outcome === "NOT_EVALUATED") {
    await expect(page.getByTestId("outcome-headline")).toHaveText(`Not evaluated — claim allowed: ${body.decision.claim_allowed}`);
  }

  // Rows: exactly the backend policies, in the backend order (PPO only if the backend returned it).
  const rows = await page.locator("[data-policy-row]").evaluateAll((els) => els.map((e) => e.getAttribute("data-policy-row")));
  expect(rows).toEqual(body.policies.map((p) => p.policy_id));

  // Identity strip and provenance.
  const identity = page.getByTestId("evaluation-identity");
  if (body.scenario_set_id) await expect(identity).toContainText(body.scenario_set_id);
  if (body.preregistration_sha256) await expect(identity).toContainText(body.preregistration_sha256);
  await expect(page.locator("[data-provenance-badge]").first()).toHaveAttribute("data-provenance-badge", body.origin === "simulated" ? "simulated" : "unverified");
  if (body.origin === "simulated") await expect(page.getByText("Simulator-only").first()).toBeVisible();
});
