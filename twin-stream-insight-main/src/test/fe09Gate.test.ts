/** Static gates for FE-09: nothing in the touched what-if / optimisation surfaces may imply superiority or safety. */
import { describe, expect, it } from "vitest";

const files = import.meta.glob(
  [
    "../components/WhatIfTab.tsx",
    "../components/DashboardSidebar.tsx",
    "../components/shell/SimulationPanel.tsx",
    "../components/scenario/ScenarioSliders.tsx",
    "../components/optimization/OptimizationCard.tsx",
    "../hooks/useWhatIf.ts",
  ],
  { query: "?raw", import: "default", eager: true }
) as Record<string, string>;
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");

describe("FE-09 source gates", () => {
  it("scans the touched files", () => expect(Object.keys(files)).toHaveLength(6));

  it.each([
    ["aiOptimizer switch", /aiOptimizer|<Switch\b/],
    ["success colouring", /text-success|bg-success|border-success|text-green|bg-green/],
    ["verdict wording", /emits less|Lower CO|Recommendation|recommend|\bwinner\b|\bbetter\b/i],
    ["'optimized/optimised' claims", /\boptimi[sz]ed\b|\bAI-/i],
    ["client carbon maths", /\*\s*475|475\s*\*|total_co2_kg\s*[<>]/],
    ["Math.random", /Math\.random/],
  ])("no %s", (_name, re) => {
    for (const [path, src] of Object.entries(files)) expect(strip(src), path).not.toMatch(re);
  });
});
