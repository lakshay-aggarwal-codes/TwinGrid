import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OperationsConsole } from "./OperationsConsole";

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
