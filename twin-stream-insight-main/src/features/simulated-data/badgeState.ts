import { classifyOrigin } from "@/provenance/model";

/**
 * The header badge says "Simulated data" only when the backend itself reported `origin: "simulated"`. The
 * classification is the provenance module's (`classifyOrigin`), so an absent, unknown or differently-cased origin
 * can never be shown as simulated -- and this module never claims anything else: it shows the badge or nothing.
 */
export function isSimulatedOrigin(origin: unknown): boolean {
  return classifyOrigin(origin).state === "simulated";
}
