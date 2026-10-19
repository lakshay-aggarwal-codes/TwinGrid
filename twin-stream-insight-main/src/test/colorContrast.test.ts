import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");

/** Task 15: axe found the login error at 3.84:1 (--destructive on the dark card). Error TEXT uses --destructive-text, which must stay >= 4.5:1. */
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  return [f(0), f(8), f(4)];
}
const lum = ([r, g, b]: [number, number, number]) => {
  const c = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
};
const ratio = (a: [number, number, number], b: [number, number, number]) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
/** The value of `--name: H S% L%` inside the block that starts at `selector`. */
function token(selector: string, name: string): [number, number, number] {
  const block = css.slice(css.indexOf(selector));
  const m = new RegExp(`--${name}:\\s*(\\d+(?:\\.\\d+)?)\\s+(\\d+(?:\\.\\d+)?)%\\s+(\\d+(?:\\.\\d+)?)%`).exec(block);
  if (!m) throw new Error(`--${name} not found after ${selector}`);
  return hslToRgb(Number(m[1]), Number(m[2]), Number(m[3]));
}

describe("destructive text contrast", () => {
  it("dark theme: --destructive-text reaches 4.5:1 on --card and --background", () => {
    const sel = ":root";
    expect(ratio(token(sel, "destructive-text"), token(sel, "card"))).toBeGreaterThanOrEqual(4.5);
    expect(ratio(token(sel, "destructive-text"), token(sel, "background"))).toBeGreaterThanOrEqual(4.5);
  });
  it("light theme: --destructive-text reaches 4.5:1 on --card", () => {
    const sel = ':root[data-theme="light"]';
    expect(ratio(token(sel, "destructive-text"), token(sel, "card"))).toBeGreaterThanOrEqual(4.5);
  });
});
