/** Task 25: tariff settings kept in this browser, and their validation. PURE (storage access is in `useTariff`). Mirrors the backend limits; the backend validates again. */
export interface TariffSettings {
  readonly currency: string;
  readonly offPeakRate: number;
  readonly peakRate: number;
  readonly peakStartHour: number;
  readonly peakEndHour: number;
  readonly demandChargePerKw: number;
  readonly billingDays: number;
}

/** Same defaults as `src/economics/tariff.py`. Illustrative, not a quote. */
export const DEFAULT_TARIFF: TariffSettings = {
  currency: "USD",
  offPeakRate: 0.08,
  peakRate: 0.18,
  peakStartHour: 16,
  peakEndHour: 21,
  demandChargePerKw: 12,
  billingDays: 30,
};

export const STORAGE_KEY = "twingrid.economics.tariff.v1";
export const ILLUSTRATIVE_LABEL = "illustrative tariff, not a quote";

export type TariffField = keyof TariffSettings;
export type Draft = Readonly<Record<TariffField, string>>;
export type DraftErrors = Partial<Record<TariffField, string>>;

export const toDraft = (t: TariffSettings): Draft => ({
  currency: t.currency,
  offPeakRate: String(t.offPeakRate),
  peakRate: String(t.peakRate),
  peakStartHour: String(t.peakStartHour),
  peakEndHour: String(t.peakEndHour),
  demandChargePerKw: String(t.demandChargePerKw),
  billingDays: String(t.billingDays),
});

const num = (s: string): number => (s.trim() === "" ? Number.NaN : Number(s));

/** Form text to settings, or one message per bad field. Nothing is repaired or clamped. */
export function validateDraft(d: Draft): { ok: true; tariff: TariffSettings } | { ok: false; errors: DraftErrors } {
  const errors: DraftErrors = {};
  const currency = d.currency.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) errors.currency = "Use a three-letter code such as USD.";
  const rate = (k: "offPeakRate" | "peakRate" | "demandChargePerKw", max: number) => {
    const v = num(d[k]);
    if (!Number.isFinite(v) || v < 0 || v > max) errors[k] = `Enter a number from 0 to ${max}.`;
    return v;
  };
  const offPeakRate = rate("offPeakRate", 1000);
  const peakRate = rate("peakRate", 1000);
  const demandChargePerKw = rate("demandChargePerKw", 100000);
  const hour = (k: "peakStartHour" | "peakEndHour") => {
    const v = num(d[k]);
    if (!Number.isInteger(v) || v < 0 || v > 24) errors[k] = "Enter a whole hour from 0 to 24.";
    return v;
  };
  const peakStartHour = hour("peakStartHour");
  const peakEndHour = hour("peakEndHour");
  const billingDays = num(d.billingDays);
  if (!Number.isInteger(billingDays) || billingDays < 1 || billingDays > 366) errors.billingDays = "Enter a whole number of days from 1 to 366.";
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return { ok: true, tariff: { currency, offPeakRate, peakRate, peakStartHour, peakEndHour, demandChargePerKw, billingDays } };
}

/** A stored value, or the defaults when it is missing or damaged (a bad entry is dropped, never repaired). */
export function parseStored(text: string | null): TariffSettings {
  if (!text) return DEFAULT_TARIFF;
  try {
    const raw: unknown = JSON.parse(text);
    if (typeof raw !== "object" || raw === null) return DEFAULT_TARIFF;
    const r = raw as Record<string, unknown>;
    const draft = Object.fromEntries((Object.keys(DEFAULT_TARIFF) as TariffField[]).map((k) => [k, typeof r[k] === "string" || typeof r[k] === "number" ? String(r[k]) : ""])) as Record<TariffField, string>;
    const v = validateDraft(draft);
    return v.ok ? v.tariff : DEFAULT_TARIFF;
  } catch {
    return DEFAULT_TARIFF;
  }
}

export const serialize = (t: TariffSettings): string => JSON.stringify(t);

export const isDefaultTariff = (t: TariffSettings): boolean => (Object.keys(DEFAULT_TARIFF) as TariffField[]).every((k) => t[k] === DEFAULT_TARIFF[k]);

/** Query parameters of `GET /api/economics/summary`. */
export const tariffQuery = (t: TariffSettings): Record<string, string> => ({
  currency: t.currency,
  off_peak_rate: String(t.offPeakRate),
  peak_rate: String(t.peakRate),
  peak_start_hour: String(t.peakStartHour),
  peak_end_hour: String(t.peakEndHour),
  demand_charge_per_kw: String(t.demandChargePerKw),
  billing_days: String(t.billingDays),
});

/** Money for display; falls back to "12.34 XYZ" if the runtime does not know the currency code. */
export function formatMoney(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

export type SavingsWording = { readonly kind: "saves" | "costs-more" | "same"; readonly text: string };

/** Words, not only a sign or colour: positive savings = the scenario costs less than the baseline. */
export function savingsWording(totalSavings: number, pct: number | null, currency: string): SavingsWording {
  const rounded = Math.round(totalSavings * 100) / 100;
  if (rounded === 0) return { kind: "same", text: "Same cost as the baseline" };
  const amount = formatMoney(Math.abs(rounded), currency);
  const p = pct === null ? "" : ` (${Math.abs(pct).toFixed(1)} %)`;
  return rounded > 0 ? { kind: "saves", text: `Saves ${amount} per day vs baseline${p}` } : { kind: "costs-more", text: `Costs ${amount} more per day than baseline${p}` };
}
