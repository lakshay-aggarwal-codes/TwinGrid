// CI gate: fail on any high/critical npm advisory that is not waived in docs/frontend/waivers/npm_audit.md.
// `npm audit` has no ignore list, so the waived GHSA ids and their expiry are listed here and must match that file.
// Usage: node scripts/npm-audit-gate.mjs [--from-file audit.json]   (the file option is for tests)
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const WAIVED = {
  // id: expiry (the gate fails after this date, forcing a re-check)
  "GHSA-mrhx-c7xc-m3w5": "2027-01-13", // zod: memory exhaustion on oversized arrays; no patched release listed
  "GHSA-vfj7-8cjw-p6xm": "2027-01-13", // braces (build-time only)
};

const fromFile = process.argv.indexOf("--from-file");
const raw =
  fromFile > 0
    ? readFileSync(process.argv[fromFile + 1], "utf8")
    : spawnSync("npm", ["audit", "--json"], { encoding: "utf8", shell: process.platform === "win32" }).stdout;
const report = JSON.parse(raw);
const today = new Date().toISOString().slice(0, 10);
const problems = [];
const used = new Set();

for (const [name, v] of Object.entries(report.vulnerabilities ?? {})) {
  if (v.severity !== "high" && v.severity !== "critical") continue;
  const own = (v.via ?? []).filter((x) => typeof x === "object");
  if (own.length === 0) continue; // only inherited from another package; that package is checked on its own
  for (const adv of own) {
    const id = String(adv.url ?? "").split("/").pop();
    const expiry = WAIVED[id];
    if (!expiry) problems.push(`${name}: ${v.severity} ${id || adv.title} is not waived`);
    else if (today > expiry) problems.push(`${name}: waiver for ${id} expired ${expiry}`);
    else used.add(id);
  }
}

if (used.size) console.log(`waived (docs/frontend/waivers/npm_audit.md): ${[...used].join(", ")}`);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("npm audit gate: no unwaived high/critical advisories");
