/**
 * Task 29: contracts for `/api/admin/*` (api/plugins/admin_console.py). Shape only; values are never defaulted.
 * Unknown extra fields are tolerated; a missing or mistyped field is a contract error, never repaired.
 */
import { z } from "zod";

const int = z.number().int();
const nstr = z.string().nullable();

export const UserSchema = z
  .object({ id: int, username: z.string(), role: z.string(), created_at: nstr, is_you: z.boolean() })
  .passthrough();
export const UsersSchema = z
  .object({ users: z.array(UserSchema), truncated: z.boolean(), roles: z.array(z.string()), counts: z.record(int) })
  .passthrough();

export const AuditItemSchema = z
  .object({
    id: int,
    created_at: nstr,
    username: nstr,
    action: z.string(),
    outcome: z.string(),
    resource_type: nstr,
    resource_id: nstr,
    client_ip: nstr,
    request_id: nstr,
    details: z.record(z.unknown()).nullable(),
  })
  .passthrough();
export const AuditSchema = z
  .object({
    items: z.array(AuditItemSchema),
    has_more: z.boolean(),
    next_before_id: int.nullable(),
    limit: int,
    actions: z.array(z.string()),
    outcomes: z.array(z.string()),
  })
  .passthrough();

export const DeliverySchema = z
  .object({
    at: z.string(),
    kind: z.enum(["alert", "test"]),
    webhook_id: z.string(),
    host: z.string(),
    ok: z.boolean(),
    status_code: int.nullable(),
    error_kind: nstr,
    duration_ms: int,
  })
  .passthrough();
export const WebhookSchema = z
  .object({ id: z.string(), scheme: z.string(), host: z.string(), port: int.nullable(), last_delivery: DeliverySchema.nullable() })
  .passthrough();
export const WebhooksSchema = z
  .object({ webhooks: z.array(WebhookSchema), max: int, fires_for_simulated_alerts: z.boolean() })
  .passthrough();
export const DeliveriesSchema = z.object({ deliveries: z.array(DeliverySchema), note: z.string() }).passthrough();
export const TestResultSchema = z
  .object({ webhook_id: z.string(), ok: z.boolean(), status_code: int.nullable(), error_kind: nstr, duration_ms: int })
  .passthrough();

const readiness = z
  .object({
    status: z.string(),
    checks: z.record(z.string()),
    degraded: z.array(z.string()),
    components: z.record(z.string()),
    timestamp: z.string(),
  })
  .passthrough();
const registryEntry = z
  .object({
    name: z.string().nullable(),
    kind: nstr,
    version: z.union([z.string(), z.number()]).nullable(),
    status: nstr,
    created_at_utc: nstr,
    physics_version: nstr,
  })
  .passthrough();
export const SystemSchema = z
  .object({
    readiness: readiness.nullable(),
    migration: z.object({ head: nstr, database: nstr, at_head: z.boolean() }).passthrough().nullable(),
    versions: z
      .object({ app: z.string(), title: z.string(), physics: nstr, safety_envelope: z.string(), python: z.string() })
      .passthrough(),
    uptime: z.object({ started_at: z.string(), seconds: int, basis: z.string() }).passthrough(),
    models: z.object({ state: z.record(z.string()).nullable(), registry: z.array(registryEntry).nullable() }).passthrough(),
    docs: z.object({ swagger: z.string(), redoc: z.string(), openapi: z.string() }).passthrough(),
    unavailable: z.array(z.string()),
  })
  .passthrough();

export type User = z.output<typeof UserSchema>;
export type Users = z.output<typeof UsersSchema>;
export type AuditItem = z.output<typeof AuditItemSchema>;
export type AuditPage = z.output<typeof AuditSchema>;
export type Delivery = z.output<typeof DeliverySchema>;
export type Webhook = z.output<typeof WebhookSchema>;
export type Webhooks = z.output<typeof WebhooksSchema>;
export type Deliveries = z.output<typeof DeliveriesSchema>;
export type TestResult = z.output<typeof TestResultSchema>;
export type SystemStatus = z.output<typeof SystemSchema>;
