/**
 * Task 15 test fixtures. CAPTURED from the real backend code on SIMULATED data (api.services.twin_service.compute_whatif and
 * src.whatif_sweep.run_sweep at the backend default inputs, carbon fallback active). They prove shape and arithmetic only;
 * they are not measurements and must never be shown as such.
 */
import type { WhatIfResponse } from "@/api/apiClient";
import type { Sweep } from "./schema";

export const CAPTURED_SWEEP: Sweep = {
  "label": "model estimate on simulated data",
  "basis": "One-at-a-time sweep: each input is moved alone, the others stay at the baseline; every run is the same 24 h constant-input isolated twin run as /api/whatif. Interactions between inputs are not captured.",
  "runs": 11,
  "max_runs": 12,
  "inputs": {
    "utilisation": 0.65,
    "outside_temp_C": 22.0,
    "water_stress": 0.0,
    "mode": "auto",
    "chilled_water_temp_C": 7.0
  },
  "outlet_limit_C": 45.0,
  "carbon_data_is_real": false,
  "baseline": {
    "mean_pue": 1.321550439044979,
    "total_energy_kwh": 12528.29816214626,
    "total_co2_kg": 5950.941627019469,
    "max_outlet_temp_C": 36.73735821275013,
    "thermal_margin_C": 8.26264178724987
  },
  "parameters": [
    {
      "parameter": "utilisation",
      "label": "Server utilisation (fraction of capacity)",
      "unit": null,
      "base": 0.65,
      "variants": [
        {
          "direction": "low",
          "value": 0.55,
          "metrics": {
            "mean_pue": 1.3183006311264907,
            "total_energy_kwh": 11548.31352866802,
            "total_co2_kg": 5485.448926117308,
            "max_outlet_temp_C": 36.0580787391602,
            "thermal_margin_C": 8.941921260839798
          },
          "deltas": {
            "mean_pue": -0.00324980791848839,
            "total_energy_kwh": -979.9846334782396,
            "total_co2_kg": -465.49270090216123,
            "max_outlet_temp_C": -0.6792794735899292,
            "thermal_margin_C": 0.6792794735899292
          }
        },
        {
          "direction": "high",
          "value": 0.75,
          "metrics": {
            "mean_pue": 1.324867291711332,
            "total_energy_kwh": 13513.646375455606,
            "total_co2_kg": 6418.982028341437,
            "max_outlet_temp_C": 37.36289249722085,
            "thermal_margin_C": 7.637107502779152
          },
          "deltas": {
            "mean_pue": 0.003316852666352954,
            "total_energy_kwh": 985.3482133093457,
            "total_co2_kg": 468.0404013219686,
            "max_outlet_temp_C": 0.6255342844707172,
            "thermal_margin_C": -0.6255342844707172
          }
        }
      ]
    },
    {
      "parameter": "outside_temp",
      "label": "Outside temperature",
      "unit": "°C",
      "base": 22.0,
      "variants": [
        {
          "direction": "low",
          "value": 17.0,
          "metrics": {
            "mean_pue": 1.315119430264075,
            "total_energy_kwh": 12467.332198903441,
            "total_co2_kg": 5921.98279447914,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": -0.0064310087809040795,
            "total_energy_kwh": -60.96596324281927,
            "total_co2_kg": -28.95883254032924,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        },
        {
          "direction": "high",
          "value": 27.0,
          "metrics": {
            "mean_pue": 1.3388380970581428,
            "total_energy_kwh": 12692.185160111123,
            "total_co2_kg": 6028.787951052796,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": 0.017287658013163787,
            "total_energy_kwh": 163.88699796486253,
            "total_co2_kg": 77.84632403332762,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        }
      ]
    },
    {
      "parameter": "chilled_water_temp",
      "label": "Chilled-water setpoint",
      "unit": "°C",
      "base": 7.0,
      "variants": [
        {
          "direction": "low",
          "value": 5.0,
          "metrics": {
            "mean_pue": 1.33650627341916,
            "total_energy_kwh": 12670.079472013576,
            "total_co2_kg": 6018.287749206416,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": 0.01495583437418091,
            "total_energy_kwh": 141.78130986731594,
            "total_co2_kg": 67.34612218694747,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        },
        {
          "direction": "high",
          "value": 9.0,
          "metrics": {
            "mean_pue": 1.3078674416387952,
            "total_energy_kwh": 12398.583346735817,
            "total_co2_kg": 5889.327089699506,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": -0.013682997406183839,
            "total_energy_kwh": -129.7148154104434,
            "total_co2_kg": -61.61453731996244,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        }
      ]
    },
    {
      "parameter": "mode",
      "label": "Cooling mode",
      "unit": null,
      "base": "auto",
      "variants": [
        {
          "direction": "alternative",
          "value": "free_air",
          "metrics": {
            "mean_pue": 1.321550439044979,
            "total_energy_kwh": 12528.29816214626,
            "total_co2_kg": 5950.941627019469,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": 0.0,
            "total_energy_kwh": 0.0,
            "total_co2_kg": 0.0,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        },
        {
          "direction": "alternative",
          "value": "closed_loop",
          "metrics": {
            "mean_pue": 1.2858226124844225,
            "total_energy_kwh": 12189.598366352231,
            "total_co2_kg": 5790.059224017347,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": -0.03572782656055651,
            "total_energy_kwh": -338.69979579402934,
            "total_co2_kg": -160.88240300212146,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        },
        {
          "direction": "alternative",
          "value": "evaporative",
          "metrics": {
            "mean_pue": 1.3481448362592197,
            "total_energy_kwh": 12780.413047737373,
            "total_co2_kg": 6070.696197675239,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": 0.026594397214240617,
            "total_energy_kwh": 252.1148855911124,
            "total_co2_kg": 119.7545706557703,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        },
        {
          "direction": "alternative",
          "value": "hybrid",
          "metrics": {
            "mean_pue": 1.321550439044979,
            "total_energy_kwh": 12528.29816214626,
            "total_co2_kg": 5950.941627019469,
            "max_outlet_temp_C": 36.73735821275013,
            "thermal_margin_C": 8.26264178724987
          },
          "deltas": {
            "mean_pue": 0.0,
            "total_energy_kwh": 0.0,
            "total_co2_kg": 0.0,
            "max_outlet_temp_C": 0.0,
            "thermal_margin_C": 0.0
          }
        }
      ]
    }
  ]
};

export const CAPTURED_WHATIF: WhatIfResponse = {
  "hours": 24,
  "basis": "24h at constant inputs, isolated digital-twin run (no RL optimizer applied)",
  "mean_pue": 1.321550439044979,
  "wue": 0.959936814485056,
  "total_water_L": 9100.201001318335,
  "total_energy_kwh": 12528.29816214626,
  "total_co2_kg": 5950.941627019469,
  "max_outlet_temp_C": 36.73735821275013,
  "final_cooling_mode": "hybrid",
  "drought_override_active": false,
  "carbon_data_is_real": false
};

export const whatIfWith = (over: Partial<WhatIfResponse>): WhatIfResponse => ({ ...CAPTURED_WHATIF, ...over });
