import { useEffect, useState } from 'react';
import { fetchWhatIf, type WhatIfResponse } from '@/api/apiClient';
import { coolingModeToApi, type SimConfig } from '@/hooks/useSimulation';

export interface WhatIfState {
  data: WhatIfResponse | null;
  loading: boolean;
  error: string | null;
}

/**
 * Real scenario result for one configuration: a debounced GET /api/whatif
 * (an isolated 24h digital-twin run on the backend). Nothing is computed
 * locally. Changing the config aborts the in-flight request so a slow older
 * response can never overwrite a newer one. On error the last good result is
 * kept alongside the error message.
 */
export function useWhatIf(cfg: SimConfig, debounceMs = 400): WhatIfState {
  const [state, setState] = useState<WhatIfState>({ data: null, loading: true, error: null });

  const { serverUtil, outsideTemp, waterStress, coolingMode, chilledWaterSetpoint } = cfg;

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));

    const timer = setTimeout(async () => {
      try {
        const data = await fetchWhatIf(
          {
            utilisation: serverUtil / 100,
            outside_temp: outsideTemp,
            water_stress: waterStress,
            mode: coolingModeToApi(coolingMode),
            chilled_water_temp: chilledWaterSetpoint,
          },
          controller.signal
        );
        setState({ data, loading: false, error: null });
      } catch (e) {
        if (controller.signal.aborted) return;
        setState((prev) => ({
          data: prev.data,
          loading: false,
          error: e instanceof Error ? e.message : 'What-if request failed',
        }));
      }
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [serverUtil, outsideTemp, waterStress, coolingMode, chilledWaterSetpoint, debounceMs]);

  return state;
}
