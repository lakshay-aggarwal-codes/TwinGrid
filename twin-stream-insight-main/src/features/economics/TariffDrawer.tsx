import { useEffect, useId, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { DEFAULT_TARIFF, ILLUSTRATIVE_LABEL, toDraft, validateDraft, type Draft, type DraftErrors, type TariffField, type TariffSettings } from "./tariff";

const BTN =
  "rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const FIELDS: readonly { key: TariffField; label: string; hint: string; mode: "text" | "decimal" | "numeric" }[] = [
  { key: "currency", label: "Currency code", hint: "Three letters, e.g. USD. A label only: nothing is converted.", mode: "text" },
  { key: "offPeakRate", label: "Off-peak energy rate (per kWh)", hint: "In the currency above.", mode: "decimal" },
  { key: "peakRate", label: "Peak energy rate (per kWh)", hint: "In the currency above.", mode: "decimal" },
  { key: "peakStartHour", label: "Peak window starts (hour, 0-24)", hint: "Hour of the simulated day, start included.", mode: "numeric" },
  { key: "peakEndHour", label: "Peak window ends (hour, 0-24)", hint: "End excluded. Start after end wraps midnight; equal means no peak window.", mode: "numeric" },
  { key: "demandChargePerKw", label: "Demand charge (per kW of peak, per billing period)", hint: "Prorated to the one simulated day.", mode: "decimal" },
  { key: "billingDays", label: "Billing period (days)", hint: "Used to prorate the demand charge.", mode: "numeric" },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tariff: TariffSettings;
  storageOk: boolean;
  onSave: (t: TariffSettings) => void;
  onReset: () => void;
}

/** Tariff settings. Nothing is applied until Save; invalid fields are named, never clamped. */
export function TariffDrawer({ open, onOpenChange, tariff, storageOk, onSave, onReset }: Props) {
  const uid = useId();
  const [draft, setDraft] = useState<Draft>(() => toDraft(tariff));
  const [errors, setErrors] = useState<DraftErrors>({});
  useEffect(() => {
    if (open) {
      setDraft(toDraft(tariff));
      setErrors({});
    }
  }, [open, tariff]);

  const save = () => {
    const v = validateDraft(draft);
    if (v.ok === false) return setErrors(v.errors);
    onSave(v.tariff);
    onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Tariff settings</SheetTitle>
          <SheetDescription>
            Defaults are an {ILLUSTRATIVE_LABEL}. Your values are kept in this browser only and are still not a quote.
          </SheetDescription>
        </SheetHeader>
        <form
          className="mt-4 space-y-3"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          {FIELDS.map((f) => {
            const id = `${uid}-${f.key}`;
            const err = errors[f.key];
            return (
              <div key={f.key} className="space-y-1">
                <label htmlFor={id} className="text-xs font-medium text-foreground">{f.label}</label>
                <Input
                  id={id}
                  value={draft[f.key]}
                  inputMode={f.mode}
                  autoComplete="off"
                  aria-invalid={err ? true : undefined}
                  aria-describedby={`${id}-hint${err ? ` ${id}-err` : ""}`}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
                <p id={`${id}-hint`} className="text-[11px] text-muted-foreground">{f.hint}</p>
                {err && <p id={`${id}-err`} role="alert" className="text-[11px] font-medium text-destructive-text">Error: {err}</p>}
              </div>
            );
          })}
          {!storageOk && <p role="status" className="text-xs text-muted-foreground">This browser would not store the tariff; it applies until you reload.</p>}
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="submit" className={BTN}>Save tariff</button>
            <button
              type="button"
              className={BTN}
              onClick={() => {
                onReset();
                setDraft(toDraft(DEFAULT_TARIFF));
                setErrors({});
              }}
            >
              Reset to defaults
            </button>
            <button type="button" className={BTN} onClick={() => onOpenChange(false)}>Cancel</button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
