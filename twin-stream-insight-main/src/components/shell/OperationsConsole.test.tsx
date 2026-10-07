import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationsConsole } from "./OperationsConsole";
import { SimulationContext, type SimulationValue } from "@/hooks/simulationContext";
import type { AnomalyStatusPayload } from "@/api/apiClient";

describe("OperationsConsole (T0b optimization label)", () => {
  it("labels optimization as experimental and simulator-only", () => {
    render(
      <OperationsConsole
        open
        onClose={() => {}}
        liveState={null}
        anomalyScore={0}
        latestAnomaly={null}
        events={[]}
        onOpenSimulationLab={() => {}}
        onGenerateReport={() => {}}
      />,
    );
    expect(screen.getByText("Experimental — simulator-only")).toBeTruthy();
    expect(screen.queryByText(/real trained RL policy/i)).toBeNull();
  });
});

const renderWith = (anomalyStatus: AnomalyStatusPayload | null) =>
  render(
    <SimulationContext.Provider value={{ anomalyStatus } as unknown as SimulationValue}>
      <OperationsConsole
        open
        onClose={() => {}}
        liveState={null}
        anomalyScore={0}
        latestAnomaly={null}
        events={[]}
        onOpenSimulationLab={() => {}}
        onGenerateReport={() => {}}
      />
    </SimulationContext.Provider>,
  );

describe("OperationsConsole anomaly block (FE-07)", () => {
  it("shows no detector status as 'not reported', never 'No active alert' or a /100 gauge", () => {
    const { container } = render(
      <OperationsConsole open onClose={() => {}} liveState={null} anomalyScore={0} latestAnomaly={null} events={[]} onOpenSimulationLab={() => {}} onGenerateReport={() => {}} />,
    );
    expect(screen.getByText("Detector status not reported")).toBeTruthy();
    expect(container.textContent).not.toMatch(/No active alert|\/ 100|Gauge:/);
  });

  it.each([
    ["unavailable", "Detector unavailable", "alert"],
    ["error", "Detector error", "alert"],
    ["recalibrating", "Unrecognised detector status", "status"],
  ])("%s is visible as a fail-closed state", (status, label, role) => {
    const { container } = renderWith({ status, message: "m", score: null, threshold: null, type: null });
    expect(screen.getByText(label)).toBeTruthy();
    expect(container.querySelector(`[data-anomaly-kind] [role="${role}"]`)).not.toBeNull();
    expect(container.textContent).not.toMatch(/No anomaly flagged|No active alert|nominal/i);
  });

  it("scored states show score beside the backend threshold and detector provenance", () => {
    const { container } = renderWith({ status: "ok", message: "m", score: 0.0123, threshold: 0.01, type: null, trained_on: "synthetic", model_version: "ae-1", origin: "simulated" });
    expect(screen.getByText("score 0.0123 / threshold 0.0100")).toBeTruthy();
    expect(container.textContent).toContain("Experimental — trained on simulator data");
    expect(container.textContent).toContain("Model version: ae-1");
    expect(container.textContent).not.toContain("%");
  });
});
