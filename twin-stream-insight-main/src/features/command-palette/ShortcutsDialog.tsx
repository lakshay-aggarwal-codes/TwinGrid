import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { BUILT_IN_SHORTCUTS, type ShortcutInfo } from "./shortcuts";

interface ShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Shortcut hints that features attached to their commands (display only; the feature binds the key). */
  extra?: readonly ShortcutInfo[];
}

/** The `?` dialog. Escape or the close button dismisses it; focus returns to where it was. */
export function ShortcutsDialog({ open, onOpenChange, extra = [] }: ShortcutsDialogProps) {
  const rows = [...BUILT_IN_SHORTCUTS, ...extra];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Shortcuts that work anywhere in the app once you are signed in.</DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-2 text-sm">
          {rows.map((r) => (
            <div key={`${r.keys}|${r.description}`} className="contents">
              <dt>
                <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">{r.keys}</kbd>
              </dt>
              <dd className="text-muted-foreground">{r.description}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
