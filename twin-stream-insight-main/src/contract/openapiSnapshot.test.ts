/**
 * FE-11: typed endpoints (auth, facility) are Pydantic models on the backend. Their OpenAPI property names, committed
 * by `scripts/capture-contract.mjs`, must match the zod schemas: every property the backend REQUIRES must exist in the
 * schema, and every key the schema requires must exist on the backend. A mismatch is a contract finding, not a reason
 * to loosen the schema.
 */
import { describe, expect, it } from 'vitest';
import type { z } from 'zod';
import { Asset, AssetsResponse, Edge, EdgesResponse, Facility, LocatedIn, Pose, TokenResponse } from './index';

interface Snapshot {
  schemas: Record<string, { properties: string[]; required: string[] }>;
}
const modules = import.meta.glob('./fixtures/openapi/typed.json', { eager: true, import: 'default' }) as Record<string, Snapshot>;
const snapshot = Object.values(modules)[0];

const PAIRS: Array<[string, z.ZodObject<z.ZodRawShape>]> = [
  ['TokenResponse', TokenResponse],
  ['FacilityOut', Facility],
  ['PoseOut', Pose],
  ['LocatedInOut', LocatedIn],
  ['AssetOut', Asset],
  ['AssetsResponse', AssetsResponse],
  ['EdgeOut', Edge],
  ['EdgesResponse', EdgesResponse],
] as Array<[string, z.ZodObject<z.ZodRawShape>]>;

describe.skipIf(snapshot === undefined)('OpenAPI typed-model snapshot vs zod schemas', () => {
  it.each(PAIRS.map(([name, schema]) => [name, schema] as const))('%s', (name, schema) => {
    const model = snapshot.schemas[name];
    expect(model, `${name} is missing from the committed OpenAPI snapshot`).toBeDefined();
    const shape = schema.shape;
    const missingInSchema = model.required.filter((p) => !(p in shape));
    const requiredBySchemaOnly = Object.entries(shape)
      .filter(([, t]) => !(t as z.ZodTypeAny).isOptional())
      .map(([k]) => k)
      .filter((k) => !model.properties.includes(k));
    expect(missingInSchema, `backend-required properties absent from the zod schema`).toEqual([]);
    expect(requiredBySchemaOnly, `schema-required keys the backend does not declare`).toEqual([]);
  });
});

describe('OpenAPI snapshot status', () => {
  it.skipIf(snapshot !== undefined)('NO OpenAPI snapshot committed yet: run scripts/capture-contract.mjs against a live backend', () => {
    /* skipped on purpose so the report shows the gap instead of a false pass */
  });
});
