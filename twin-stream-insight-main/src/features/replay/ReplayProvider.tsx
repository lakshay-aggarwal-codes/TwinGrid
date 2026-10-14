import type { ReactNode } from "react";
import { ReplayContext } from "./ReplayContext";
import { useReplayController } from "./useReplayController";

/** Owns the replay for the page it wraps. Leaving the page unmounts it: replay never carries over to a page that shows live values. */
export function ReplayProvider({ children }: { children: ReactNode }) {
  const value = useReplayController();
  return <ReplayContext.Provider value={value}>{children}</ReplayContext.Provider>;
}
