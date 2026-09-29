import type { ReactNode } from "react";
import { useSimulation } from "@/hooks/useSimulation";
import { SimulationContext } from "./simulationContext.ts";

/**
 * Stage 16: owns the one and only `useSimulation()` instance (one WebSocket,
 * one anomaly buffer, one set of slider values). Mounted above <Routes>, so it
 * survives page changes.
 */
export function SimulationProvider({ children }: { children: ReactNode }) {
  const value = useSimulation();
  return <SimulationContext.Provider value={value}>{children}</SimulationContext.Provider>;
}
