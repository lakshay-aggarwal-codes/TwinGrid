import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "@/state/useApiQuery";
import {
  AUDIT_ROOT,
  DELIVERIES_ROOT,
  KEYS,
  changeRole,
  createWebhook,
  deleteWebhook,
  fetchAudit,
  fetchDeliveries,
  fetchSystem,
  fetchUsers,
  fetchWebhooks,
  replaceWebhook,
  testWebhook,
} from "./api";
import type { AuditPage, Deliveries, SystemStatus, Users, Webhooks } from "./schema";

export function useUsers() {
  return useApiQuery<Users>({
    queryKey: KEYS.users,
    queryFn: ({ signal }) => fetchUsers(signal),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
    isEmpty: (u) => u.users.length === 0,
  });
}

/** `query` is a built, validated query string; `enabled=false` makes no request. */
export function useAudit(query: string, enabled = true) {
  return useApiQuery<AuditPage>({
    queryKey: KEYS.audit(query),
    queryFn: ({ signal }) => fetchAudit(query, signal),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    isEmpty: (p) => p.items.length === 0,
  });
}

export function useWebhooks() {
  return useApiQuery<Webhooks>({
    queryKey: KEYS.webhooks,
    queryFn: ({ signal }) => fetchWebhooks(signal),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    isEmpty: (w) => w.webhooks.length === 0,
  });
}

export function useDeliveries(webhookId: string | null) {
  return useApiQuery<Deliveries>({
    queryKey: KEYS.deliveries(webhookId),
    queryFn: ({ signal }) => fetchDeliveries(webhookId, signal),
    staleTime: 5_000,
    refetchOnWindowFocus: false,
    isEmpty: (d) => d.deliveries.length === 0,
  });
}

export function useSystem() {
  return useApiQuery<SystemStatus>({
    queryKey: KEYS.system,
    queryFn: ({ signal }) => fetchSystem(signal),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

/** Writes resolve to the SERVER's answer; the lists are then refetched, never patched optimistically. */
export function useUserActions() {
  const client = useQueryClient();
  const setRole = useCallback(
    async (id: number, role: string) => {
      const row = await changeRole(id, role);
      await client.invalidateQueries({ queryKey: KEYS.users });
      await client.invalidateQueries({ queryKey: AUDIT_ROOT });
      return row;
    },
    [client],
  );
  return { setRole };
}

export function useWebhookActions() {
  const client = useQueryClient();
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: KEYS.webhooks });
    await client.invalidateQueries({ queryKey: DELIVERIES_ROOT });
    await client.invalidateQueries({ queryKey: AUDIT_ROOT });
  }, [client]);
  const create = useCallback(async (url: string) => {
    const r = await createWebhook(url);
    await refresh();
    return r;
  }, [refresh]);
  const replace = useCallback(async (id: string, url: string) => {
    const r = await replaceWebhook(id, url);
    await refresh();
    return r;
  }, [refresh]);
  const remove = useCallback(async (id: string) => {
    const r = await deleteWebhook(id);
    await refresh();
    return r;
  }, [refresh]);
  const test = useCallback(async (id: string) => {
    const r = await testWebhook(id);
    await refresh();
    return r;
  }, [refresh]);
  return { create, replace, remove, test };
}
