import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

interface SimulationParams {
  utilisation?: number;
  inlet_temp?: number;
  cooling_mode?: 'free_air' | 'closed_loop' | 'evaporative';
}

function runSimulation(params: SimulationParams) {
  const utilisation = params.utilisation || 0.7;
  const inlet_temp = params.inlet_temp || 20;
  const cooling_mode = params.cooling_mode || 'closed_loop';

  const it_power_kw = 250 * (0.4 + 0.6 * utilisation);

  const outlet_temp = inlet_temp + (it_power_kw * 1000) / (1.2 * 8 * 1005);

  const cop_map = {
    free_air: 8,
    closed_loop: 4.5,
    evaporative: 3.5
  };
  const cop = cop_map[cooling_mode];
  const cooling_power_kw = it_power_kw / cop;

  const evap_rate_map = {
    free_air: 0,
    closed_loop: 0.001,
    evaporative: 0.03
  };
  const evap_rate = evap_rate_map[cooling_mode];
  const water_consumed_L = cooling_power_kw * 5 * evap_rate;

  const total_power_kw = it_power_kw + cooling_power_kw;
  const pue = total_power_kw / it_power_kw;

  const wue = it_power_kw > 0 ? water_consumed_L / it_power_kw : 0;

  return {
    pue: parseFloat(pue.toFixed(3)),
    wue: parseFloat(wue.toFixed(3)),
    it_power_kw: parseFloat(it_power_kw.toFixed(2)),
    cooling_power_kw: parseFloat(cooling_power_kw.toFixed(2)),
    water_consumed_L: parseFloat(water_consumed_L.toFixed(2)),
    outlet_temp: parseFloat(outlet_temp.toFixed(2)),
    cooling_mode
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
    const url = new URL(req.url);
    const utilisation = parseFloat(url.searchParams.get('utilisation') || '0.7');
    const inlet_temp = parseFloat(url.searchParams.get('inlet_temp') || '20');
    const cooling_mode = (url.searchParams.get('cooling_mode') || 'closed_loop') as 'free_air' | 'closed_loop' | 'evaporative';

    const result = runSimulation({ utilisation, inlet_temp, cooling_mode });

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
