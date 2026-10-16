/**
 * Task 21: colour-blind-safe chart colours. These are the Okabe-Ito palette (Okabe & Ito, 2002), designed to stay
 * distinguishable under the common colour-vision deficiencies. Colour is still never the only cue: charts also use
 * dash patterns, fill patterns and text (see SimulationTab, HistoryLegend).
 */
export const CB = {
  orange: "#E69F00",
  skyBlue: "#56B4E9",
  bluishGreen: "#009E73",
  yellow: "#F0E442",
  blue: "#0072B2",
  vermillion: "#D55E00",
  reddishPurple: "#CC79A7",
  grey: "#999999",
} as const;

/** Line colours that keep at least 3:1 against both the dark and the light card (checked in chartPalette.test.ts). */
export const LINE_COLORS = [CB.vermillion, CB.bluishGreen, CB.reddishPurple] as const;

/** Series order for charts that need N colours; the first entries are the most mutually distinct. */
export const CB_SERIES: readonly string[] = [CB.orange, CB.skyBlue, CB.bluishGreen, CB.reddishPurple, CB.vermillion, CB.blue, CB.yellow, CB.grey];

/** Cooling-mode colours (SimulationTab). Pattern fills carry the same distinction without colour. */
export const MODE_COLORS = {
  evaporative: CB.skyBlue,
  closed_loop: CB.reddishPurple,
  free_air: CB.bluishGreen,
  hybrid: CB.orange,
  unrecognised: CB.grey,
} as const;

/** Chart chrome follows the theme tokens, so axes, grid and tooltips work in both dark and light. */
export const CHART_CHROME = {
  grid: "hsl(var(--border))",
  axis: "hsl(var(--muted-foreground))",
  /** Outline for filled marks, so a light fill keeps an edge against a light card. */
  outline: "hsl(var(--foreground) / 0.55)",
  tooltip: {
    backgroundColor: "hsl(var(--popover))",
    border: "1px solid hsl(var(--border))",
    borderRadius: 8,
    color: "hsl(var(--popover-foreground))",
  },
  tooltipText: "hsl(var(--popover-foreground))",
  tooltipLabel: "hsl(var(--muted-foreground))",
} as const;

/** WCAG relative luminance contrast ratio of two #RRGGBB colours (used by tests). */
export function contrastRatio(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
