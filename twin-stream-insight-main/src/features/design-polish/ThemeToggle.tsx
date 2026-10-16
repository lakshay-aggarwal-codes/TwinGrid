import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import type { SlotWidgetProps } from "../types";
import { applyTheme, readStoredTheme, storeTheme, type Theme } from "./theme";

/** Header action: switches between the dark and light theme. The accessible name states the action, `aria-pressed` the state. */
export default function ThemeToggle(_props: SlotWidgetProps) {
  const [theme, setTheme] = useState<Theme>(() => (typeof document === "undefined" ? "dark" : readStoredTheme()));
  const light = theme === "light";
  const toggle = () => {
    const next: Theme = light ? "dark" : "light";
    applyTheme(next);
    storeTheme(next);
    setTheme(next);
  };
  const Icon = light ? Sun : Moon;
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={light}
      aria-label="Light theme"
      title={light ? "Switch to dark theme" : "Switch to light theme"}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
    </button>
  );
}
