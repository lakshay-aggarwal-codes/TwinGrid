import { Anchor } from "@radix-ui/react-popover";
import { ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";
import { Popover, PopoverContent } from "@/components/ui/popover";
import type { TourPhase, TourProgress, TourStep } from "./engine";
import type { Box } from "./useTargetRect";

const PAD = 6;

interface TourOverlayProps {
  step: TourStep;
  phase: Extract<TourPhase, "playing" | "paused">;
  progress: TourProgress;
  /** Where the highlighted element is; null -> no highlight, caption centred. */
  box: Box | null;
  onNext: () => void;
  onPrev: () => void;
  onToggle: () => void;
  onSkip: () => void;
}

const seconds = (ms: number) => `${Math.ceil(ms / 1000)} s`;

/**
 * The spotlight and the caption card. The spotlight is decorative (aria-hidden, no pointer events, so the page stays
 * usable); the card is a Radix popover anchored to the highlighted element, with real buttons for every control.
 * No CSS animation runs here; the one transition is switched off under prefers-reduced-motion.
 */
export function TourOverlay({ step, phase, progress, box, onNext, onPrev, onToggle, onSkip }: TourOverlayProps) {
  const last = progress.position === progress.total;
  const first = progress.position === 1;
  const anchorStyle = box
    ? { top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 }
    : { top: "45%", left: "50%", width: 0, height: 0 };

  return (
    <>
      {box ? (
        <div
          aria-hidden="true"
          data-testid="tour-spotlight"
          className="pointer-events-none fixed z-[45] rounded-md ring-2 ring-primary shadow-[0_0_0_9999px_rgba(0,0,0,0.55)] transition-[top,left,width,height] duration-300 motion-reduce:transition-none"
          style={anchorStyle}
        />
      ) : (
        <div aria-hidden="true" data-testid="tour-dim" className="pointer-events-none fixed inset-0 z-[45] bg-black/55" />
      )}
      <Popover open>
        <Anchor asChild>
          <div aria-hidden="true" className="pointer-events-none fixed" style={anchorStyle} />
        </Anchor>
        <PopoverContent
          side="bottom"
          align="center"
          sideOffset={12}
          collisionPadding={12}
          aria-label="Story mode"
          data-testid="tour-card"
          className="w-[min(22rem,calc(100vw-1.5rem))] space-y-3"
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => {
            e.preventDefault();
            onSkip();
          }}
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Story mode · step {progress.position} of {progress.total}
              {phase === "paused" ? " · Paused" : ` · next in ${seconds(progress.remainingStepMs)}`}
            </p>
            <button
              type="button"
              onClick={onSkip}
              aria-label="Skip tour"
              className="-m-1 rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </button>
          </div>

          <div aria-live="polite" aria-atomic="true" className="space-y-1">
            <h2 className="text-sm font-semibold text-foreground">{step.title}</h2>
            <p className="text-xs leading-relaxed text-muted-foreground">{step.caption}</p>
          </div>

          <div
            role="progressbar"
            aria-label="Story progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress.fraction * 100)}
            className="h-1 w-full overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full bg-primary" style={{ width: `${Math.round(progress.fraction * 100)}%` }} />
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <TourButton onClick={onPrev} disabled={first} label="Back" icon={<ChevronLeft aria-hidden="true" className="h-3.5 w-3.5" />} />
            <TourButton
              onClick={onToggle}
              label={phase === "playing" ? "Pause" : "Resume"}
              icon={phase === "playing" ? <Pause aria-hidden="true" className="h-3.5 w-3.5" /> : <Play aria-hidden="true" className="h-3.5 w-3.5" />}
            />
            <TourButton onClick={onNext} label={last ? "Finish" : "Next"} primary icon={last ? undefined : <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />} iconAfter />
            <button
              type="button"
              onClick={onSkip}
              className="ml-auto rounded-sm px-1 text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Skip tour
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground">Keys: ← back · → next · P pause or resume · Esc skip</p>
        </PopoverContent>
      </Popover>
    </>
  );
}

function TourButton({ onClick, label, icon, disabled, primary, iconAfter }: { onClick: () => void; label: string; icon?: React.ReactNode; disabled?: boolean; primary?: boolean; iconAfter?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 ${
        primary ? "border-primary bg-primary text-primary-foreground hover:bg-primary/90" : "border-border text-foreground hover:bg-accent"
      }`}
    >
      {!iconAfter && icon}
      {label}
      {iconAfter && icon}
    </button>
  );
}
