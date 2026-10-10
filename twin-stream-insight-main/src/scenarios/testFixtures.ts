/** Test-only: the real G-SCN capture (docs/frontend/contracts/G-SCN.capture-scenarios.json), byte-identical. */
import type { ScenarioRegistry } from './schema';

const modules = import.meta.glob('./fixtures/scenarios.json', { eager: true, import: 'default' }) as Record<string, ScenarioRegistry>;

export const CAPTURED_REGISTRY: ScenarioRegistry = Object.values(modules)[0];

export const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
