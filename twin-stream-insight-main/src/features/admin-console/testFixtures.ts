/** Test fixtures only (not imported by the app). Shapes mirror `/api/admin/*`. */
import type { AuditPage, Deliveries, Delivery, SystemStatus, TestResult, Users, Webhooks } from "./schema";

export const usersFixture = (): Users => ({
  users: [
    { id: 1, username: "admin1", role: "admin", created_at: "2026-01-01T00:00:00+00:00", is_you: true },
    { id: 2, username: "alice", role: "viewer", created_at: "2026-01-02T00:00:00+00:00", is_you: false },
    { id: 3, username: "bob", role: "operator", created_at: null, is_you: false },
    { id: 4, username: "zed", role: "root", created_at: "2026-01-03T00:00:00+00:00", is_you: false },
  ],
  truncated: false,
  roles: ["viewer", "operator", "admin"],
  counts: { viewer: 1, operator: 1, admin: 1 },
});

export const auditFixture = (over: Partial<AuditPage> = {}): AuditPage => ({
  items: [
    { id: 9, created_at: "2026-01-01T12:00:00+00:00", username: "=cmd|x", action: "login_failure", outcome: "failure", resource_type: null, resource_id: null, client_ip: "10.0.0.1", request_id: "r1", details: { reason: "bad password" } },
    { id: 8, created_at: "2026-01-01T11:00:00+00:00", username: "alice", action: "webhook_registered", outcome: "success", resource_type: "webhook", resource_id: "abcd", client_ip: null, request_id: null, details: null },
  ],
  has_more: true,
  next_before_id: 8,
  limit: 50,
  actions: ["login_failure", "webhook_registered"],
  outcomes: ["success", "denied", "failure"],
  ...over,
});

export const delivery = (over: Partial<Delivery> = {}): Delivery => ({
  at: "2026-01-01T12:00:00+00:00",
  kind: "test",
  webhook_id: "0123456789abcdef",
  host: "hooks.example.com",
  ok: true,
  status_code: 200,
  error_kind: null,
  duration_ms: 42,
  ...over,
});

export const webhooksFixture = (over: Partial<Webhooks> = {}): Webhooks => ({
  webhooks: [
    { id: "0123456789abcdef", scheme: "https", host: "hooks.example.com", port: null, last_delivery: delivery() },
    { id: "fedcba9876543210", scheme: "https", host: "other.example.com", port: 8443, last_delivery: null },
  ],
  max: 20,
  fires_for_simulated_alerts: false,
  ...over,
});

export const deliveriesFixture = (): Deliveries => ({
  deliveries: [delivery(), delivery({ ok: false, status_code: 500, error_kind: "http_error", kind: "alert", at: "2026-01-01T11:00:00+00:00" })],
  note: "Recent attempts, newest first, kept in a bounded file. With several API workers it is partial.",
});

export const testResult = (over: Partial<TestResult> = {}): TestResult => ({
  webhook_id: "0123456789abcdef",
  ok: true,
  status_code: 200,
  error_kind: null,
  duration_ms: 12,
  ...over,
});

export const systemFixture = (over: Partial<SystemStatus> = {}): SystemStatus => ({
  readiness: {
    status: "ready",
    checks: { database: "ok", schema: "ok", broadcast: "ok" },
    degraded: ["anomaly_detector"],
    components: { redis: "not_configured", optimizer: "loaded", anomaly_detector: "degraded" },
    timestamp: "2026-01-01T12:00:00+00:00",
  },
  migration: { head: "20261008000000", database: "20261008000000", at_head: true },
  versions: { app: "1.0.0", title: "Digital Twin API", physics: "1", safety_envelope: "2", python: "3.12.1" },
  uptime: { started_at: "2026-01-01T10:00:00+00:00", seconds: 7500, basis: "since this process loaded the API plugins" },
  models: { state: { optimizer: "loaded" }, registry: [{ name: "ppo", kind: "ppo", version: "3", status: "promoted", created_at_utc: null, physics_version: "1" }] },
  docs: { swagger: "/docs", redoc: "/redoc", openapi: "/openapi.json" },
  unavailable: [],
  ...over,
});
