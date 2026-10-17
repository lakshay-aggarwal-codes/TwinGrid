import { describe, expect, it } from "vitest";
import { AuditSchema, DeliveriesSchema, SystemSchema, TestResultSchema, UserSchema, UsersSchema, WebhooksSchema } from "./schema";
import { auditFixture, deliveriesFixture, systemFixture, testResult, usersFixture, webhooksFixture } from "./testFixtures";

describe("contracts", () => {
  it("accept well-formed bodies, extra fields included", () => {
    expect(UsersSchema.safeParse({ ...usersFixture(), extra: 1 }).success).toBe(true);
    expect(UserSchema.safeParse(usersFixture().users[0]).success).toBe(true);
    expect(AuditSchema.safeParse(auditFixture()).success).toBe(true);
    expect(WebhooksSchema.safeParse(webhooksFixture()).success).toBe(true);
    expect(DeliveriesSchema.safeParse(deliveriesFixture()).success).toBe(true);
    expect(TestResultSchema.safeParse(testResult()).success).toBe(true);
    expect(SystemSchema.safeParse(systemFixture()).success).toBe(true);
  });
  it("accept the degraded system body (parts the server could not read)", () => {
    const degraded = systemFixture({ readiness: null, migration: null, models: { state: null, registry: null }, unavailable: ["readiness", "migration", "model_registry"] });
    expect(SystemSchema.safeParse(degraded).success).toBe(true);
  });
  it("reject a missing field, a wrong type and an unknown delivery kind", () => {
    const { users: _u, ...noUsers } = usersFixture();
    expect(UsersSchema.safeParse(noUsers).success).toBe(false);
    expect(AuditSchema.safeParse({ ...auditFixture(), has_more: "yes" }).success).toBe(false);
    const w = webhooksFixture();
    expect(WebhooksSchema.safeParse({ ...w, webhooks: [{ ...w.webhooks[0], port: "443" }] }).success).toBe(false);
    expect(DeliveriesSchema.safeParse({ ...deliveriesFixture(), deliveries: [{ ...deliveriesFixture().deliveries[0], kind: "other" }] }).success).toBe(false);
    expect(SystemSchema.safeParse({ ...systemFixture(), uptime: { started_at: "x", seconds: 1.5, basis: "y" } }).success).toBe(false);
  });
  it("a webhook body has no field that could hold a URL path (the browser never learns it)", () => {
    const keys = Object.keys(webhooksFixture().webhooks[0]);
    expect(keys.sort()).toEqual(["host", "id", "last_delivery", "port", "scheme"]);
  });
});
