import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchEquipmentHealth, type EquipmentHealthResponse } from "@/api/apiClient";
import { useApiQuery } from "@/state/useApiQuery";
import { HEALTH_HOURS, ORDERS_ROOT, changeWorkOrderStatus, createWorkOrder, fetchMaintenanceHealth, fetchWorkOrders, healthKey, ordersKey } from "./api";
import type { CreateBody } from "./model";
import type { Health, WorkOrder } from "./schema";

export const HEALTH_STALE_MS = 30_000;

export function useHealth() {
  return useApiQuery<Health>({
    queryKey: healthKey(HEALTH_HOURS),
    queryFn: ({ signal }) => fetchMaintenanceHealth(HEALTH_HOURS, signal),
    staleTime: HEALTH_STALE_MS,
    refetchOnWindowFocus: false,
    isEmpty: (h) => h.assets.length === 0,
  });
}

export function useWorkOrders(status: string | null) {
  return useApiQuery<WorkOrder[]>({
    queryKey: ordersKey(status),
    queryFn: ({ signal }) => fetchWorkOrders(status, signal),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    isEmpty: (rows) => rows.length === 0,
  });
}

/** The existing equipment-health service: the model's methodology metrics on a proxy dataset (not per-asset health). */
export function useEquipmentModel() {
  return useApiQuery<EquipmentHealthResponse>({
    queryKey: ["equipment-health"],
    queryFn: ({ signal }) => fetchEquipmentHealth(signal),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/** Writes resolve to the SERVER's row; the lists are then refetched, never patched optimistically. */
export function useWorkOrderActions() {
  const client = useQueryClient();
  const create = useCallback(
    async (body: CreateBody): Promise<WorkOrder> => {
      const row = await createWorkOrder(body);
      await client.invalidateQueries({ queryKey: ORDERS_ROOT });
      return row;
    },
    [client],
  );
  const setStatus = useCallback(
    async (id: number, status: string, note: string | null = null): Promise<WorkOrder> => {
      const row = await changeWorkOrderStatus(id, status, note);
      await client.invalidateQueries({ queryKey: ORDERS_ROOT });
      return row;
    },
    [client],
  );
  return { create, setStatus };
}
