/**
 * FE-11: the contract-drift gate's own tests. `scripts/capture-contract.mjs --diff` is what CI runs after re-capturing
 * from the compose backend; these prove it FAILS on drift (a deliberately mutated fixture) and passes on identical shapes.
 * The synthetic bodies below exercise the comparator only; they are not backend data.
 */
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { compareFixtureDirs, compareOpenapiSnapshots, diffShapes, shapeOf, typedOpenapiSnapshot, TYPED_OPENAPI_MODELS } from '../../scripts/capture-contract.mjs';

const dirs: string[] = [];
const tmp = () => {
  const d = mkdtempSync(join(tmpdir(), 'drift-'));
  dirs.push(d);
  return d;
};
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop() as string, { recursive: true, force: true });
});

const meta = { endpoint: '/api/state', method: 'GET', http_status: 200, captured_at: '2026-01-01T00:00:00Z', base_url_host: 'localhost:8000', backend_hash: null, redactions: [] };
const writeFixture = (dir: string, name: string, body: unknown, over: Record<string, unknown> = {}) =>
  writeFileSync(join(dir, `${name}.json`), JSON.stringify({ _meta: { ...meta, ...over }, body }));

const base = { pue: 1.2, cooling_mode: 'auto', origin: 'simulated', items: [{ a: 1 }], note: null };

describe('shapeOf / diffShapes', () => {
  it('ignores values, compares structure', () => {
    expect(diffShapes(shapeOf(base), shapeOf({ ...base, pue: 9.9, cooling_mode: 'hybrid', items: [{ a: 7 }] }))).toEqual([]);
  });

  it('reports a removed key, an added key and a type change with their paths', () => {
    const { cooling_mode: _removed, ...rest } = base;
    const d = diffShapes(shapeOf(base), shapeOf({ ...rest, extra: 1, pue: '1.2' }));
    expect(d).toEqual(expect.arrayContaining(['removed  $.cooling_mode', 'added    $.extra', 'type     $.pue: number -> string']));
  });

  it('treats null and empty arrays as compatible with any shape (they say nothing about the type)', () => {
    expect(diffShapes(shapeOf({ n: null, list: [] }), shapeOf({ n: 5, list: [{ a: 1 }] }))).toEqual([]);
    expect(diffShapes(shapeOf({ n: 5, list: [{ a: 1 }] }), shapeOf({ n: null, list: [] }))).toEqual([]);
  });

  it('unions the keys of array elements and still finds a change inside them', () => {
    expect(diffShapes(shapeOf({ items: [{ a: 1 }, { b: 2 }] }), shapeOf({ items: [{ a: 1, b: 2 }] }))).toEqual([]);
    expect(diffShapes(shapeOf({ items: [{ a: 1 }] }), shapeOf({ items: [{ a: 'x' }] }))).toEqual(['type     $.items[].a: number -> string']);
  });
});

describe('compareFixtureDirs (the CI drift check)', () => {
  it('passes when the fresh capture has the same shapes', () => {
    const [c, f] = [tmp(), tmp()];
    writeFixture(c, 'state', base);
    writeFixture(f, 'state', { ...base, pue: 1.9 });
    expect(compareFixtureDirs(c, f)).toEqual([]);
  });

  it('FAILS on a deliberately mutated fixture (required field removed)', () => {
    const [c, f] = [tmp(), tmp()];
    writeFixture(c, 'state', base);
    const { pue: _pue, ...mutated } = base;
    writeFixture(f, 'state', mutated);
    expect(compareFixtureDirs(c, f)).toEqual(['state: removed  $.pue']);
  });

  it('fails when an endpoint, method or status changed', () => {
    const [c, f] = [tmp(), tmp()];
    writeFixture(c, 'state', base);
    writeFixture(f, 'state', base, { http_status: 201 });
    expect(compareFixtureDirs(c, f)).toEqual(['state: _meta.http_status 200 -> 201']);
  });

  it('fails when a committed fixture was not re-captured, and when a fresh one is not committed', () => {
    const [c, f] = [tmp(), tmp()];
    writeFixture(c, 'state', base);
    writeFixture(f, 'whatif', base);
    const findings = compareFixtureDirs(c, f);
    expect(findings.some((x: string) => x.startsWith('state: committed fixture has no fresh capture'))).toBe(true);
    expect(findings.some((x: string) => x.startsWith('whatif: fresh capture is not committed'))).toBe(true);
  });

  it('fails when nothing is committed: drift cannot be measured against nothing', () => {
    const [c, f] = [tmp(), tmp()];
    writeFixture(f, 'state', base);
    expect(compareFixtureDirs(c, f)[0]).toMatch(/no committed fixtures/);
  });
});

describe('OpenAPI snapshot', () => {
  const snapshot = (props: string[], required: string[]) => ({
    schemas: Object.fromEntries(TYPED_OPENAPI_MODELS.map((n: string) => [n, { properties: props, required }])),
  });
  const write = (dir: string, s: unknown) => {
    mkdirSync(join(dir, 'openapi'), { recursive: true });
    writeFileSync(join(dir, 'openapi', 'typed.json'), JSON.stringify(s));
    return join(dir, 'openapi', 'typed.json');
  };

  it('reduces a full OpenAPI document to the typed models, sorted', () => {
    const spec = { components: { schemas: { TokenResponse: { properties: { role: {}, access_token: {} }, required: ['role', 'access_token'] }, Other: { properties: { x: {} } } } } };
    expect(typedOpenapiSnapshot(spec)).toEqual({ TokenResponse: { properties: ['access_token', 'role'], required: ['access_token', 'role'] } });
  });

  it('passes on identical property names and fails on an added, removed or newly required property', () => {
    const [a, b] = [tmp(), tmp()];
    const committed = write(a, snapshot(['id', 'name'], ['id']));
    expect(compareOpenapiSnapshots(committed, write(b, snapshot(['id', 'name'], ['id'])))).toEqual([]);
    const drift = compareOpenapiSnapshots(committed, write(tmp(), snapshot(['id', 'extra'], ['id', 'extra'])));
    expect(drift).toEqual(expect.arrayContaining(['openapi TokenResponse: property removed name', 'openapi TokenResponse: property added extra', 'openapi TokenResponse: extra became required']));
  });

  it('fails when a snapshot is missing', () => {
    expect(compareOpenapiSnapshots(join(tmp(), 'nope.json'), join(tmp(), 'nope2.json'))[0]).toMatch(/no committed OpenAPI snapshot/);
  });
});

describe('committed fixtures (once captured): every one is covered by the drift gate', () => {
  const fixtureDir = join(__dirname, 'fixtures');
  const files = readdirSync(fixtureDir).filter((f) => f.endsWith('.json'));

  it.skipIf(files.length === 0)('mutating any committed fixture is detected', () => {
    for (const file of files) {
      const copy = tmp();
      cpSync(fixtureDir, copy, { recursive: true });
      const parsed = JSON.parse(readFileSync(join(copy, file), 'utf8')) as { body: unknown };
      const target = Array.isArray(parsed.body) ? parsed.body[0] : parsed.body;
      if (typeof target !== 'object' || target === null) continue; // an empty list has no shape to mutate
      delete (target as Record<string, unknown>)[Object.keys(target)[0]];
      writeFileSync(join(copy, file), JSON.stringify(parsed));
      expect(compareFixtureDirs(fixtureDir, copy).some((x: string) => x.startsWith(file.replace(/\.json$/, '')))).toBe(true);
    }
  });

  it.skipIf(files.length > 0)('NO committed fixtures yet: the contract job fails until a real capture is committed', () => {
    /* skipped on purpose so the report shows the gap */
  });
});
