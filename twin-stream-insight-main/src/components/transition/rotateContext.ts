import { createContext, useContext } from "react";

export type Direction = 1 | -1;

export type RotateNavigate = (to: string, direction?: Direction) => void;

export const RotateContext = createContext<RotateNavigate | null>(null);

export function useRotateNavigate(): RotateNavigate {
  const ctx = useContext(RotateContext);
  if (!ctx) throw new Error("useRotateNavigate must be used inside <RotateTransition>");
  return ctx;
}
