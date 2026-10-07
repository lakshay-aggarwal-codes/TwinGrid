/** FE-04 test helpers: a controllable fake transport and clock. Test-only. */
import type { LiveStatePayload, SocketStatus, TransportState } from '@/api/apiClient';
import type { Clock } from './freshness';

export function liveFrame(extra: Partial<LiveStatePayload> = {}): LiveStatePayload {
  return {
    timestamp: '2026-01-01T12:35:00',
    server_utilisation: 0.5,
    outside_temp_C: 22,
    server_inlet_temp_C: 20,
    server_outlet_temp_C: 30,
    it_power_kw: 300,
    cooling_power_kw: 60,
    total_power_kw: 360,
    pue: 1.2,
    water_flow_lpm: 10,
    water_consumed_L: 5,
    wue: 0.1,
    humidity_pct: 50,
    water_pressure_bar: 3,
    cooling_mode: 'hybrid',
    anomaly: 0,
    interval_s: 3,
    ...extra,
  };
}

export function transportState(extra: Partial<TransportState> = {}): TransportState {
  return { status: 'open', reason: null, lastCloseCode: null, attempt: 0, nextRetryAt: null, backend: 'unknown', ...extra };
}

export function fakeClock(start = 1000): Clock & { advance(ms: number): void } {
  let t = start;
  return { now: () => t, advance: (ms) => void (t += ms) };
}

export function fakeTransport() {
  const h = {
    connects: 0,
    disconnects: 0,
    onMessage: null as null | ((f: LiveStatePayload) => void),
    onStatus: null as null | ((s: SocketStatus) => void),
    onTransport: null as null | ((t: TransportState) => void),
  };
  const connect = ((onMessage: (f: LiveStatePayload) => void, onStatus?: (s: SocketStatus) => void, onTransport?: (t: TransportState) => void) => {
    h.connects += 1;
    h.onMessage = onMessage;
    h.onStatus = onStatus ?? null;
    h.onTransport = onTransport ?? null;
    return { disconnect: () => void (h.disconnects += 1), getState: () => transportState() };
  }) as typeof import('@/api/apiClient').connectWebSocket;
  return { h, connect };
}
