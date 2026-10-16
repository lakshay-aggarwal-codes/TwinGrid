import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useRole } from "@/hooks/useAuth.ts";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { isEditableTarget } from "../command-palette/shortcuts";
import { CORE_ROUTE_PATHS, featureRegistry, type FeatureRegistry } from "../registry";
import { roleAllows } from "../roles";
import { IDLE_TOUR, currentStep, resolveSteps, resumeIndex, tourProgress, tourReducer, type TourStep } from "./engine";
import { subscribeTourRequests } from "./requests";
import { STORY_STEPS } from "./steps";
import { loadTourPrefs, saveTourPrefs, type TourPrefs } from "./storage";
import { TourOverlay } from "./TourOverlay";
import { useTargetRect } from "./useTargetRect";
import { WelcomeDialog } from "./WelcomeDialog";

/** Auto-advance resolution. Coarse on purpose: this is a caption timer, not an animation. */
export const TICK_MS = 500;

interface HostProps {
  /** Tests only. */
  steps?: readonly TourStep[];
  registry?: FeatureRegistry;
  tickMs?: number;
}

const restoreFocus = (el: HTMLElement | null) => {
  window.setTimeout(() => {
    if (el && el.isConnected) el.focus();
  }, 0);
};

/**
 * Mounted once (settings slot, so on every signed-in page). Owns the story state, the first-run welcome, auto-advance,
 * navigation between pages, keyboard control and the remembered "resume" point.
 */
export function TourHost({ steps: allSteps = STORY_STEPS, registry = featureRegistry, tickMs = TICK_MS }: HostProps) {
  const { role } = useRole();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [state, dispatch] = useReducer(tourReducer, IDLE_TOUR);
  const [prefs, setPrefs] = useState<TourPrefs>(() => loadTourPrefs());
  const [welcomeOpen, setWelcomeOpen] = useState(() => !loadTourPrefs().welcomeSeen);
  const returnFocus = useRef<HTMLElement | null>(null);
  const arrivedFor = useRef<string | null>(null);

  const remember = useCallback((patch: Partial<TourPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      saveTourPrefs(next);
      return next;
    });
  }, []);

  const steps = useMemo(() => {
    const paths = [...CORE_ROUTE_PATHS, ...registry.allRoutes().filter((r) => roleAllows(role, r.minRole)).map((r) => r.path)];
    return resolveSteps(allSteps, role, paths);
  }, [allSteps, registry, role]);

  const canResume = prefs.resumeStepId !== null && steps.some((s) => s.id === prefs.resumeStepId);
  const step = currentStep(state);
  const active = step !== null;

  const begin = useCallback(
    (fromIndex: number) => {
      if (steps.length === 0) return;
      const el = document.activeElement;
      returnFocus.current = el instanceof HTMLElement && el !== document.body ? el : null;
      arrivedFor.current = null;
      setWelcomeOpen(false);
      remember({ welcomeSeen: true, resumeStepId: null });
      dispatch({ type: "start", steps, fromIndex });
    },
    [steps, remember],
  );

  const skip = useCallback(() => {
    if (step) remember({ welcomeSeen: true, resumeStepId: step.id });
    dispatch({ type: "skip" });
    restoreFocus(returnFocus.current);
  }, [step, remember]);

  const dismissWelcome = useCallback(() => {
    setWelcomeOpen(false);
    remember({ welcomeSeen: true });
  }, [remember]);

  // Requests from the command palette.
  useEffect(
    () =>
      subscribeTourRequests((r) => {
        if (r === "welcome") setWelcomeOpen(true);
        else if (r === "start") begin(0);
        else begin(canResume ? resumeIndex(steps, prefs.resumeStepId) : 0);
      }),
    [begin, canResume, steps, prefs.resumeStepId],
  );

  // Go to the step's page when the step changes.
  useEffect(() => {
    if (step && pathname !== step.route && arrivedFor.current !== step.id) navigate(step.route);
    // `pathname` is deliberately not a dependency: only a step change navigates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id]);

  // On the page: remember it. Leaving it by hand ends the tour (resume stays available) instead of fighting the user.
  useEffect(() => {
    if (!step) return;
    if (pathname === step.route) arrivedFor.current = step.id;
    else if (arrivedFor.current === step.id) skip();
  }, [pathname, step, skip]);

  // Auto-advance: only while playing, on the right page, and with the tab visible.
  const playing = state.phase === "playing";
  const onPage = step !== null && pathname === step.route;
  useEffect(() => {
    if (!playing || !onPage) return;
    const id = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState !== "hidden") dispatch({ type: "tick", dtMs: tickMs });
    }, tickMs);
    return () => clearInterval(id);
  }, [playing, onPage, tickMs, step?.id]);

  // Finished: remember it and hand focus back.
  useEffect(() => {
    if (state.phase === "finished") remember({ completed: true, resumeStepId: null, welcomeSeen: true });
  }, [state.phase, remember]);

  // Keyboard: arrows and P. Escape is the popover's own handler. Typing in a field and Ctrl/Cmd/Alt combos are left alone.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isEditableTarget(e.target)) return;
      if (e.key === "ArrowRight") dispatch({ type: "next" });
      else if (e.key === "ArrowLeft") dispatch({ type: "prev" });
      else if (e.key === "p" || e.key === "P") dispatch({ type: "toggle" });
      else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active]);

  const box = useTargetRect(step?.targets, active && onPage, step?.id ?? "");
  const closeFinished = () => {
    dispatch({ type: "close" });
    restoreFocus(returnFocus.current);
  };

  return (
    <>
      <WelcomeDialog
        open={welcomeOpen && !active}
        role={role}
        canResume={canResume}
        onStart={() => begin(0)}
        onResume={() => begin(resumeIndex(steps, prefs.resumeStepId))}
        onDismiss={dismissWelcome}
      />
      {step && (state.phase === "playing" || state.phase === "paused") && (
        <TourOverlay
          step={step}
          phase={state.phase}
          progress={tourProgress(state)}
          box={onPage ? box : null}
          onNext={() => dispatch({ type: "next" })}
          onPrev={() => dispatch({ type: "prev" })}
          onToggle={() => dispatch({ type: "toggle" })}
          onSkip={skip}
        />
      )}
      <Dialog open={state.phase === "finished"} onOpenChange={(o) => !o && closeFinished()}>
        <DialogContent data-testid="tour-finished">
          <DialogHeader>
            <DialogTitle>That is the tour</DialogTitle>
            <DialogDescription>
              You have seen the main pages. Press Ctrl+K at any time to jump somewhere, or start Story Mode again from the same palette.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <button
              type="button"
              onClick={() => begin(0)}
              className="inline-flex items-center rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Watch again
            </button>
            <button
              type="button"
              onClick={closeFinished}
              className="inline-flex items-center rounded-md border border-primary bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Close
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
