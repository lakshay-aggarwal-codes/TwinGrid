import { createContext, useContext } from "react";
import type { useSimulation } from "@/hooks/useSimulation";

/** Everything `useSimulation()` returns, shared app-wide (Stage 16). */
export type SimulationValue = ReturnType<typeof useSimulation>;

export const SimulationContext = createContext<SimulationValue | null>(null);

/**
 * Read the single shared simulation/live-feed state. Both pages use this
 * instead of calling `useSimulation()` directly, so navigating between them
 * neither reconnects the WebSocket nor resets the sliders.
 */
export function useSharedSimulation(): SimulationValue {
  const ctx = useContext(SimulationContext);
  if (!ctx) throw new Error("useSharedSimulation must be used inside <SimulationProvider>");
  return ctx;
}
