/** R3 Task 2: `GET /api/whatif` now names its physics version and provenance. Both stay optional (older backends). */
import { describe, expect, it } from 'vitest';

import { WhatIfResponse } from './schemas/whatif';

const base = {
  hours: 24,
  basis: 'b',
  mean_pue: 1.3,
  wue: 0.4,
  total_water_L: 1000,
  total_energy_kwh: 5000,
  total_co2_kg: 100,
  max_outlet_temp_C: 33,
  final_cooling_mode: 'free_air',
  drought_override_active: false,
  carbon_data_is_real: false,
};

const provenance = {
  origin: 'simulated',
  scenario_kind: null,
  weather_source: 'constant_input',
  plant: 'simulated',
  control: 'none',
  model_version: null,
  registry_version: '1',
  api_version: '1.0.0',
};

describe('WhatIfResponse physics_version and provenance', () => {
  it('parses an older backend body that has neither', () => {
    expect(WhatIfResponse.safeParse(base).success).toBe(true);
  });

  it('parses a body that has both, keeping them', () => {
    const r = WhatIfResponse.safeParse({ ...base, physics_version: '1', provenance });
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.physics_version).toBe('1');
      expect(r.data.provenance?.weather_source).toBe('constant_input');
      expect(r.data.provenance?.scenario_kind).toBeNull();
    }
  });

  it('accepts a preset kind and tolerates a field it does not know', () => {
    const r = WhatIfResponse.safeParse({
      ...base,
      provenance: { ...provenance, scenario_kind: 'heat-wave', future_field: 1 },
    });
    expect(r.success).toBe(true);
  });

  it('rejects a provenance that is not an object', () => {
    expect(WhatIfResponse.safeParse({ ...base, provenance: 'simulated' }).success).toBe(false);
  });
});
