import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface WelcomeDialogProps {
  open: boolean;
  role: string | null;
  canResume: boolean;
  onStart: () => void;
  onResume: () => void;
  /** Closed without starting (any way: button, Escape, the X). */
  onDismiss: () => void;
}

const roleLine = (role: string | null): string =>
  role === "operator"
    ? "You are signed in as an operator, so the tour also shows the alert and optimizer actions you can take."
    : "You are signed in as a viewer: everything here is read-only, and the tour shows only what you can use.";

const btn = "inline-flex items-center justify-center rounded-md border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** First-run welcome. A Radix dialog, so focus is trapped while it is open and returns to the page when it closes. */
export function WelcomeDialog({ open, role, canResume, onStart, onResume, onDismiss }: WelcomeDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onDismiss()}>
      <DialogContent data-testid="tour-welcome">
        <DialogHeader>
          <DialogTitle>Welcome to TwinGrid</DialogTitle>
          <DialogDescription>
            A simulation-based digital twin of a data centre. Every number on screen comes from a simulator and is labelled that way.
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Story Mode is a guided walkthrough of about three minutes. It moves between pages, highlights what to look at and explains it. You can pause, step
          or skip at any time, and start it again later from the command palette (Ctrl+K).
        </p>
        <p className="text-sm text-muted-foreground">{roleLine(role)}</p>
        <DialogFooter className="gap-2 sm:gap-2">
          <button type="button" onClick={onDismiss} className={`${btn} border-border hover:bg-accent`}>
            Explore on my own
          </button>
          {canResume && (
            <button type="button" onClick={onResume} className={`${btn} border-border hover:bg-accent`}>
              Resume where I stopped
            </button>
          )}
          <button type="button" onClick={onStart} className={`${btn} border-primary bg-primary text-primary-foreground hover:bg-primary/90`}>
            Start Story Mode
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
