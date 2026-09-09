import { useState, useEffect, useRef } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Activity, Droplets, Zap, Thermometer, Gauge, Wind } from 'lucide-react';
import { MetricCard } from './MetricCard';
import { SimulationData } from '../types';

export function Dashboard() {
  const [liveData, setLiveData] = useState<SimulationData | null>(null);
  const [historicalData, setHistoricalData] = useState<SimulationData[]>([]);
  const [utilisation, setUtilisation] = useState(0.7);
  const [inletTemp, setInletTemp] = useState(20);
  const [coolingMode, setCoolingMode] = useState<'free_air' | 'closed_loop' | 'evaporative'>('closed_loop');
  const [waterStress, setWaterStress] = useState(1.0);
  const wsRef = useRef<WebSocket | null>(null);
  const apiUrl = import.meta.env.VITE_SUPABASE_URL;

  useEffect(() => {
    fetchHistoricalData();
  }, [coolingMode, utilisation, inletTemp]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const connectWebSocket = () => {
    const wsUrl = `${apiUrl.replace('https://', 'wss://')}/functions/v1/live`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data: SimulationData = JSON.parse(event.data);
      setLiveData(data);

      setHistoricalData((prev) => {
        const newData = [...prev, { ...data, hour: prev.length }].slice(-24);
        return newData;
      });
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('WebSocket closed, reconnecting...');
      setTimeout(connectWebSocket, 5000);
    };

    wsRef.current = ws;
  };

  const fetchHistoricalData = async () => {
    try {
      const response = await fetch(
        `${apiUrl}/functions/v1/scenario/24?utilisation=${utilisation}&inlet_temp=${inletTemp}&cooling_mode=${coolingMode}`
      );
      const data = await response.json();
      setHistoricalData(data);
    } catch (error) {
      console.error('Error fetching historical data:', error);
    }
  };

  const handleOptimize = async () => {
    try {
      const response = await fetch(`${apiUrl}/functions/v1/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          alpha: 0.4,
          beta: 0.3,
          gamma: 0.3,
          water_stress: waterStress
        })
      });
      const result = await response.json();
      alert(result.message);
    } catch (error) {
      console.error('Error optimizing:', error);
    }
  };

  const displayData = liveData || historicalData[historicalData.length - 1] || {
    pue: 0,
    wue: 0,
    it_power_kw: 0,
    cooling_power_kw: 0,
    water_consumed_L: 0,
    outlet_temp: 0,
    cooling_mode: 'closed_loop' as const
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">Data Centre Digital Twin</h1>
          <p className="text-slate-300">Real-time monitoring and optimization</p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
          <MetricCard
            title="Power Usage Effectiveness"
            value={displayData.pue}
            icon={<Gauge size={24} />}
            trend={displayData.pue < 1.3 ? 'down' : displayData.pue > 1.5 ? 'up' : 'stable'}
          />
          <MetricCard
            title="Water Usage Effectiveness"
            value={displayData.wue}
            unit="L/kWh"
            icon={<Droplets size={24} />}
            trend={displayData.wue < 1.0 ? 'down' : 'up'}
          />
          <MetricCard
            title="IT Power"
            value={displayData.it_power_kw}
            unit="kW"
            icon={<Zap size={24} />}
          />
          <MetricCard
            title="Cooling Power"
            value={displayData.cooling_power_kw}
            unit="kW"
            icon={<Wind size={24} />}
          />
          <MetricCard
            title="Water Consumed"
            value={displayData.water_consumed_L}
            unit="L"
            icon={<Droplets size={24} />}
          />
          <MetricCard
            title="Outlet Temperature"
            value={displayData.outlet_temp}
            unit="°C"
            icon={<Thermometer size={24} />}
          />
        </div>

        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 mb-8">
          <h2 className="text-xl font-bold text-white mb-4">24-Hour Trends</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={historicalData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="hour"
                stroke="#94a3b8"
                label={{ value: 'Hours', position: 'insideBottom', offset: -5, fill: '#94a3b8' }}
              />
              <YAxis stroke="#94a3b8" />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569' }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Legend />
              <Line type="monotone" dataKey="pue" stroke="#3b82f6" strokeWidth={2} name="PUE" />
              <Line type="monotone" dataKey="wue" stroke="#10b981" strokeWidth={2} name="WUE" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h2 className="text-xl font-bold text-white mb-6">Control Panel</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <div>
              <label className="block text-slate-300 mb-2">
                Utilisation: {(utilisation * 100).toFixed(0)}%
              </label>
              <input
                type="range"
                min="0.3"
                max="1.0"
                step="0.05"
                value={utilisation}
                onChange={(e) => setUtilisation(parseFloat(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
            </div>

            <div>
              <label className="block text-slate-300 mb-2">
                Inlet Temperature: {inletTemp}°C
              </label>
              <input
                type="range"
                min="15"
                max="30"
                step="1"
                value={inletTemp}
                onChange={(e) => setInletTemp(parseFloat(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
            </div>

            <div>
              <label className="block text-slate-300 mb-2">
                Water Stress Factor: {waterStress.toFixed(1)}
              </label>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.1"
                value={waterStress}
                onChange={(e) => setWaterStress(parseFloat(e.target.value))}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
            </div>

            <div>
              <label className="block text-slate-300 mb-2">Cooling Mode</label>
              <select
                value={coolingMode}
                onChange={(e) => setCoolingMode(e.target.value as any)}
                className="w-full bg-slate-700 text-white rounded-lg px-4 py-2 border border-slate-600 focus:border-blue-500 focus:outline-none"
              >
                <option value="free_air">Free Air Cooling</option>
                <option value="closed_loop">Closed Loop Cooling</option>
                <option value="evaporative">Evaporative Cooling</option>
              </select>
            </div>
          </div>

          <button
            onClick={handleOptimize}
            className="w-full md:w-auto bg-blue-600 hover:bg-blue-700 text-white font-semibold px-8 py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <Activity size={20} />
            Optimize Configuration
          </button>
        </div>
      </div>
    </div>
  );
}
