import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

interface OptimizeRequest {
  alpha: number;
  beta: number;
  gamma: number;
  water_stress: number;
}

interface SimulationResult {
  utilisation: number;
  cooling_mode: string;
  inlet_temp: number;
  pue: number;
  wue: number;
  water_consumed_L: number;
  score: number;
}

function simulate(utilisation: number, inlet_temp: number, cooling_mode: 'free_air' | 'closed_loop' | 'evaporative') {
  const it_power_kw = 250 * (0.4 + 0.6 * utilisation);
  const outlet_temp = inlet_temp + (it_power_kw * 1000) / (1.2 * 8 * 1005);

  const cop_map = { free_air: 8, closed_loop: 4.5, evaporative: 3.5 };
  const cop = cop_map[cooling_mode];
  const cooling_power_kw = it_power_kw / cop;

  const evap_rate_map = { free_air: 0, closed_loop: 0.001, evaporative: 0.03 };
  const evap_rate = evap_rate_map[cooling_mode];
  const water_consumed_L = cooling_power_kw * 5 * evap_rate;

  const total_power_kw = it_power_kw + cooling_power_kw;
  const pue = total_power_kw / it_power_kw;
  const wue = it_power_kw > 0 ? water_consumed_L / it_power_kw : 0;

  return { pue, wue, water_consumed_L, it_power_kw, cooling_power_kw, outlet_temp };
}

function optimizeActions(weights: OptimizeRequest) {
  const { alpha, beta, gamma, water_stress } = weights;

  const cooling_modes: ('free_air' | 'closed_loop' | 'evaporative')[] = ['free_air', 'closed_loop', 'evaporative'];
  const utilisations = [0.5, 0.6, 0.7, 0.8, 0.9];
  const inlet_temps = [18, 20, 22, 24, 26];

  let best: SimulationResult | null = null;
  let best_score = Infinity;

  for (const cooling_mode of cooling_modes) {
    for (const utilisation of utilisations) {
      for (const inlet_temp of inlet_temps) {
        const result = simulate(utilisation, inlet_temp, cooling_mode);

        const pue_normalized = (result.pue - 1.0) / 0.5;
        const wue_normalized = result.wue / 2.0;
        const water_penalty = water_stress * result.water_consumed_L / 100;

        const score = alpha * pue_normalized + beta * wue_normalized + gamma * water_penalty;

        if (score < best_score) {
          best_score = score;
          best = {
            utilisation,
            cooling_mode,
            inlet_temp,
            pue: parseFloat(result.pue.toFixed(3)),
            wue: parseFloat(result.wue.toFixed(3)),
            water_consumed_L: parseFloat(result.water_consumed_L.toFixed(2)),
            score: parseFloat(score.toFixed(3))
          };
        }
      }
    }
  }

  return {
    recommended_action: best,
    message: `Optimize cooling to ${best?.cooling_mode} mode, set utilisation to ${(best?.utilisation! * 100).toFixed(0)}%, inlet temp to ${best?.inlet_temp}°C`
  };
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 200,
      headers: corsHeaders,
    });
  }

  try {
    const body: OptimizeRequest = await req.json();
    const result = optimizeActions(body);

    return new Response(JSON.stringify(result), {
      headers: {
        ...corsHeaders,
        "Content-Type": "application/json",
      },
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: {
        ...corsHeaders,
        "Content-Type": "application/json",
      },
    });
  }
});
