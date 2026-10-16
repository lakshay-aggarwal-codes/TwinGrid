import { useCallback, useState } from "react";
import { DEFAULT_TARIFF, STORAGE_KEY, parseStored, serialize, type TariffSettings } from "./tariff";

function read(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** The tariff kept in this browser (a per-viewer convenience). Storage can be missing or full: the page still works, `storageOk` says so. */
export function useTariff(): { tariff: TariffSettings; storageOk: boolean; save: (t: TariffSettings) => void; reset: () => void } {
  const [tariff, setTariff] = useState<TariffSettings>(() => parseStored(read()));
  const [storageOk, setStorageOk] = useState(true);
  const save = useCallback((t: TariffSettings) => {
    setTariff(t);
    try {
      window.localStorage.setItem(STORAGE_KEY, serialize(t));
      setStorageOk(true);
    } catch {
      setStorageOk(false);
    }
  }, []);
  const reset = useCallback(() => {
    setTariff(DEFAULT_TARIFF);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      setStorageOk(true);
    } catch {
      setStorageOk(false);
    }
  }, []);
  return { tariff, storageOk, save, reset };
}
