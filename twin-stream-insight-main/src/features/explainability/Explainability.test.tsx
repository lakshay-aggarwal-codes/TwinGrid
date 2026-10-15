import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetchPassport: vi.fn(), fetchExplanation: vi.fn() }));
vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), fetchPassport: mocks.fetchPassport, fetchExplanation: mocks.fetchExplanation }));
vi.mock("@/lib/errorReporter", () => ({ reportError: vi.fn() }));

import { ApiError } from "@/api/apiError";
import { AnomalyGauge } from "@/components/AnomalyGauge";
import { AlertExplanation } from "./AlertExplanation";
import { ModelPassportButton } from "./ModelPassportButton";
import PassportHost from "./PassportHost";
import { resetPassportStore } from "./passportStore";
import { ExplanationSchema, PassportSchema } from "./model";
import passportJson from "./fixtures/passport.json";
import explanationJson from "./fixtures/explanation.json";

const passport = PassportSchema.parse(passportJson);
const explanation = ExplanationSchema.parse(explanationJson);

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mocks.fetchPassport.mockReset().mockResolvedValue(passport);
  mocks.fetchExplanation.mockReset().mockResolvedValue(explanation);
});
afterEach(() => {
  cleanup();
  resetPassportStore();
});

describe("Model Passport drawer", () => {
  it("requests nothing until a button opens it", () => {
    wrap(<PassportHost />);
    expect(mocks.fetchPassport).not.toHaveBeenCalled();
  });

  it("a widget button opens the drawer for that kind only, with status, synthetic label, limitations and boundary", async () => {
    wrap(
      <>
        <PassportHost />
        <ModelPassportButton kind="anomaly" label="Detector passport" />
      </>,
    );
    fireEvent.click(screen.getByText("Detector passport"));
    const drawer = await screen.findByTestId("passport-drawer");
    await within(drawer).findByTestId("passport-model");
    expect(within(drawer).getAllByTestId("passport-model")).toHaveLength(1);
    expect(within(drawer).getByTestId("passport-status").textContent).toMatch(/Promoted: the API may load it/);
    expect(within(drawer).getByTestId("passport-origin").textContent).toMatch(/synthetic-data result/);
    expect(within(drawer).getByText(/Headline metrics \(synthetic-data result\)/)).toBeTruthy();
    expect(within(drawer).getByText("0.9231")).toBeTruthy(); // precision, 4 significant digits
    expect(within(drawer).getAllByText(/not SHAP/i).length).toBeGreaterThan(0);
    expect(within(drawer).getByTestId("passport-boundary").textContent).toMatch(/performance on the current simulator/);
    expect(within(drawer).getByText(/Alert threshold/)).toBeTruthy();
  });

  it("PPO state comes from the stored decision and a candidate shows NOT MEASURED, never a number", async () => {
    wrap(
      <>
        <PassportHost />
        <ModelPassportButton kind="ppo" />
      </>,
    );
    fireEvent.click(screen.getAllByTestId("model-passport-button")[1]);
    const evals = await screen.findAllByTestId("passport-evaluation");
    expect(evals[0].textContent).toMatch(/NOT_EVALUATED/);
    expect(evals[0].textContent).toMatch(/claim allowed:\s*none/);
    expect(screen.getAllByTestId("passport-no-metrics").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("passport-status").some((e) => /Quarantined/.test(e.textContent ?? ""))).toBe(true);
  });

  it("'Show all models' widens the drawer", async () => {
    wrap(
      <>
        <PassportHost />
        <ModelPassportButton kind="forecaster" />
      </>,
    );
    fireEvent.click(screen.getAllByTestId("model-passport-button")[1]);
    await screen.findByTestId("passport-model");
    expect(screen.getAllByTestId("passport-details")).toHaveLength(1);
    fireEvent.click(screen.getByText("Show all models"));
    await waitFor(() => expect(screen.getAllByTestId("passport-details")).toHaveLength(8));
  });

  it("shows an error state with retry when the passport cannot be loaded", async () => {
    mocks.fetchPassport.mockRejectedValue(new ApiError({ kind: "unavailable" }));
    wrap(<PassportHost />);
    fireEvent.click(screen.getByTestId("model-passport-button"));
    await screen.findByTestId("passport-drawer");
    await waitFor(() => expect(document.querySelector('[data-state="error"], [data-state="unavailable"]')).toBeTruthy());
  });
});

describe("Why did this fire?", () => {
  it("asks for nothing until opened, then shows score vs threshold and the ranked signals", async () => {
    wrap(<AlertExplanation alertId={7} />);
    expect(mocks.fetchExplanation).not.toHaveBeenCalled();
    const btn = screen.getByRole("button", { name: /why did this fire/i });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect((await screen.findByTestId("explanation-score")).textContent).toMatch(/2\.46x the alert threshold/);
    const rows = screen.getAllByTestId("explanation-row");
    expect(rows).toHaveLength(5);
    expect(rows[0].textContent).toMatch(/Water pressure/i);
    expect(rows[0].getAttribute("data-outside")).toBe("true");
    expect(rows[0].textContent).toMatch(/Outside the range/);
    expect(screen.getAllByTestId("explanation-unavailable")[0].textContent).toMatch(/reconstruction-error shares are not stored/);
    expect(mocks.fetchExplanation).toHaveBeenCalledTimes(1);
  });

  it("says what could not be computed instead of inventing numbers", async () => {
    mocks.fetchExplanation.mockResolvedValue({ ...explanation, features: null, score_vs_threshold: null, unavailable: ["This alert is not linked to a stored sensor reading, so the per-signal deviation cannot be computed."] });
    wrap(<AlertExplanation alertId={9} />);
    fireEvent.click(screen.getByRole("button", { name: /why did this fire/i }));
    await screen.findByTestId("alert-explanation-body");
    expect(screen.queryByTestId("explanation-table")).toBeNull();
    expect(screen.queryByTestId("explanation-score")).toBeNull();
    expect(screen.getByTestId("explanation-unavailable").textContent).toMatch(/not linked to a stored sensor reading/);
  });

  it("a 404 shows an error state, not an empty explanation", async () => {
    mocks.fetchExplanation.mockRejectedValue(new ApiError({ kind: "not_found", status: 404 }));
    wrap(<AlertExplanation alertId={1} />);
    fireEvent.click(screen.getByRole("button", { name: /why did this fire/i }));
    await waitFor(() => expect(document.querySelector('[data-state="error"], [data-state="not_found"], [data-state="unavailable"]')).toBeTruthy());
    expect(screen.queryByTestId("alert-explanation-body")).toBeNull();
  });
});

describe("anomaly gauge", () => {
  const flagged = {
    status: "anomalous", message: "x", score: 0.03, threshold: 0.0122, type: "thermal_spike", window_filled: 12, window_size: 12,
    explanation: { total_error: 0.03, top_feature: "water_pressure_bar", feature_contributions_pct: { water_flow_lpm: 10, water_pressure_bar: 70, server_outlet_temp_C: 15, it_power_kw: 3, humidity_pct: 2 } },
  }; // prettier-ignore

  it("shows the detector's own breakdown only while flagging, and offers the passport", () => {
    wrap(<AnomalyGauge status={flagged as never} />);
    const rows = screen.getAllByTestId("live-why-row");
    expect(rows).toHaveLength(5);
    expect(rows[0].textContent).toMatch(/Water pressure/);
    expect(rows[0].textContent).toMatch(/70\.0%/);
    expect(screen.getByTestId("model-passport-button").getAttribute("data-kind")).toBe("anomaly");
  });

  it("shows no breakdown when the status is normal, even if an explanation were attached", () => {
    wrap(<AnomalyGauge status={{ ...flagged, status: "ok" } as never} />);
    expect(screen.queryByTestId("live-why")).toBeNull();
  });

  it("shows no breakdown when the flagged frame carries no usable explanation", () => {
    wrap(<AnomalyGauge status={{ ...flagged, explanation: null } as never} />);
    expect(screen.queryByTestId("live-why")).toBeNull();
  });
});
