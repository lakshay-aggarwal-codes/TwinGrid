import { useState, type ReactNode } from "react";
import { Clock } from "lucide-react";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { groupItems, resolveRecents, type PaletteItem } from "./items";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: readonly PaletteItem[];
  /** Ids of recently run items, most recent first. */
  recentIds: readonly string[];
  /** Called when a row is chosen (click, or Enter on the highlighted row). The host closes the palette and runs it. */
  onRun: (item: PaletteItem) => void;
  /** Data sources that must exist only while the palette is open (they may fetch). Render nothing visible. */
  sources?: ReactNode;
}

function Row({ item, prefix, onRun }: { item: PaletteItem; prefix: string; onRun: (item: PaletteItem) => void }) {
  return (
    <CommandItem value={`${prefix}${item.id}`} keywords={[...item.keywords, item.label]} onSelect={() => onRun(item)}>
      {prefix === "recent:" && <Clock aria-hidden="true" className="mr-2 h-4 w-4 text-muted-foreground" />}
      <span className="truncate">{item.label}</span>
      {item.shortcut && <span className="ml-auto font-mono text-[10px] text-muted-foreground">{item.shortcut}</span>}
    </CommandItem>
  );
}

/**
 * The palette itself: a `cmdk` dialog (fuzzy match over each row's label and keywords), grouped, with a "Recent"
 * group while the search box is empty. Presentational: the host owns open state, focus return and what a row does.
 * Radix traps focus inside and Escape closes it.
 */
export function CommandPalette({ open, onOpenChange, items, recentIds, onRun, sources }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const handleOpenChange = (next: boolean) => {
    if (!next) setQuery("");
    onOpenChange(next);
  };
  const recents = query.trim() === "" ? resolveRecents(recentIds, items) : [];

  return (
    <CommandDialog open={open} onOpenChange={handleOpenChange}>
      <DialogTitle className="sr-only">Command palette</DialogTitle>
      <DialogDescription className="sr-only">
        Type to search pages, scenarios, racks, alerts and actions. Use the arrow keys and Enter to run one. Escape closes.
      </DialogDescription>
      {sources}
      <CommandInput placeholder="Type a command or search…" value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>No matching commands.</CommandEmpty>
        {recents.length > 0 && (
          <CommandGroup heading="Recent">
            {recents.map((item) => (
              <Row key={item.id} item={item} prefix="recent:" onRun={onRun} />
            ))}
          </CommandGroup>
        )}
        {groupItems(items).map(({ group, items: rows }) => (
          <CommandGroup key={group} heading={group}>
            {rows.map((item) => (
              <Row key={item.id} item={item} prefix="" onRun={onRun} />
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
