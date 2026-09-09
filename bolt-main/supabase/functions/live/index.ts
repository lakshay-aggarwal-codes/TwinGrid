import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

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

  return {
    pue: parseFloat(pue.toFixed(3)),
    wue: parseFloat(wue.toFixed(3)),
    it_power_kw: parseFloat(it_power_kw.toFixed(2)),
    cooling_power_kw: parseFloat(cooling_power_kw.toFixed(2)),
    water_consumed_L: parseFloat(water_consumed_L.toFixed(2)),
    outlet_temp: parseFloat(outlet_temp.toFixed(2)),
    cooling_mode,
    timestamp: Date.now()
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
    const upgrade = req.headers.get("upgrade") || "";
    if (upgrade.toLowerCase() !== "websocket") {
      return new Response("Expected WebSocket connection", {
        status: 426,
        headers: corsHeaders,
      });
    }

    const { socket, response } = Deno.upgradeWebSocket(req);

    socket.onopen = () => {
      console.log("WebSocket connection opened");

      const interval = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          const utilisation = 0.6 + Math.random() * 0.3;
          const inlet_temp = 19 + Math.random() * 4;
          const cooling_modes: ('free_air' | 'closed_loop' | 'evaporative')[] = ['free_air', 'closed_loop', 'evaporative'];
          const cooling_mode = cooling_modes[Math.floor(Math.random() * cooling_modes.length)];

          const data = simulate(utilisation, inlet_temp, cooling_mode);
          socket.send(JSON.stringify(data));
        } else {
          clearInterval(interval);
        }
      }, 5000);

      socket.onclose = () => {
        clearInterval(interval);
        console.log("WebSocket connection closed");
      };
    };

    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    return response;
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
