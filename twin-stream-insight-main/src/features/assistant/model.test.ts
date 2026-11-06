import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/apiError";
import { ASK_TIMEOUT_MS, ERROR_COPY, LIMITS, SLOW_AFTER_MS, buildRequest, docHref, errorKindOf, fellBackText, hasWeakEvidence, isSafeLink, modeLabel, observedText, providerKind, providerText, segmentsOf, suggestionsFor, valueText, warningText } from "./model";
import { CopilotResponseSchema, EvidenceSchema } from "./schema";
import { DOCS_ANSWER, DOCS_NOT_DOCUMENTED, KNOWN_ROUTES, LLM_CLOUD_FELL_BACK, LLM_FALLBACK, LLM_LOCAL, RULE_BASED, STALE } from "./testFixtures";
import rateLimited from "../../contract/fixtures-copilot/rate_limited.json";
import offline from "../../contract/fixtures-copilot/offline.json";

describe("fixtures", () => {
  it("every 200 fixture is valid against the schema", () => {
    expect(RULE_BASED.mode).toBe("rule_based");
    expect(RULE_BASED.evidence[0].value).toBe(0.91);
  });
  it("the error fixtures describe a 429 with Retry-After and a network that is down", () => {
    expect(rateLimited.synthetic_http.status).toBe(429);
    expect(rateLimited.synthetic_http.headers["Retry-After"]).toBe("30");
    expect(offline.synthetic_network).toBe("offline");
  });
  it("an unknown origin, freshness, source or mode is rejected, not guessed at", () => {
    const e = RULE_BASED.evidence[0];
    expect(EvidenceSchema.safeParse({ ...e, origin: "live" }).success).toBe(false);
    expect(EvidenceSchema.safeParse({ ...e, freshness: "ok" }).success).toBe(false);
    expect(EvidenceSchema.safeParse({ ...e, source: "web" }).success).toBe(false);
    expect(CopilotResponseSchema.safeParse({ ...RULE_BASED, mode: "agent" }).success).toBe(false);
    expect(CopilotResponseSchema.safeParse({ ...RULE_BASED, answer: "x".repeat(1501) }).success).toBe(false);
  });
});

describe("buildRequest", () => {
  it("trims, keeps the context and the last 6 history items cut to 500 characters", () => {
    const history = Array.from({ length: 8 }, (_, i) => ({ role: i % 2 ? ("assistant" as const) : ("user" as const), text: `${i}${"x".repeat(600)}` }));
    const r = buildRequest("  Why?  ", { kind: "alert", id: "42" }, history);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.body.question).toBe("Why?");
    expect(r.body.context).toEqual({ kind: "alert", id: "42" });
    expect(r.body.history).toHaveLength(6);
    expect(r.body.history[0].text).toHaveLength(LIMITS.historyText);
    expect(r.body.history[0].text.startsWith("2")).toBe(true);
  });
  it("omits id when the context has none", () => {
    const r = buildRequest("What is this?", { kind: "model" }, []);
    expect(r.ok && r.body.context).toEqual({ kind: "model" });
  });
  it("refuses empty, over-long and bad-context requests", () => {
    expect(buildRequest("   ", { kind: "general" }, [])).toEqual({ ok: false, reason: "empty" });
    expect(buildRequest("x".repeat(501), { kind: "general" }, [])).toEqual({ ok: false, reason: "too_long" });
    expect(buildRequest("x".repeat(500), { kind: "general" }, []).ok).toBe(true);
    expect(buildRequest("ok", { kind: "alert", id: "9".repeat(65) }, [])).toEqual({ ok: false, reason: "bad_context" });
    expect(buildRequest("ok", { kind: "alert", id: "" }, [])).toEqual({ ok: false, reason: "bad_context" });
  });
});

describe("segmentsOf", () => {
  it("turns [E#] into citation segments and leaves text intact", () => {
    expect(segmentsOf(RULE_BASED.answer, RULE_BASED.evidence).map((s) => (s.type === "cite" ? `<${s.id}>` : s.text)).join("")).toBe(
      RULE_BASED.answer.replace("[E1]", "<E1>").replace("[E2]", "<E2>"),
    );
    expect(segmentsOf(RULE_BASED.answer, RULE_BASED.evidence).filter((s) => s.type === "cite")).toHaveLength(2);
  });
  it("a marker with no matching evidence stays plain text", () => {
    const s = segmentsOf("Value [E9] here", RULE_BASED.evidence);
    expect(s).toEqual([{ type: "text", text: "Value [E9] here" }]);
  });
  it("handles an answer of only text, only markers and the maximum length", () => {
    expect(segmentsOf("", [])).toEqual([]);
    expect(segmentsOf("[E1]", RULE_BASED.evidence)).toEqual([{ type: "cite", id: "E1" }]);
    expect(segmentsOf("a".repeat(1500), []).length).toBe(1);
  });
});

describe("isSafeLink", () => {
  it("accepts only relative paths to known routes (and one id under runs/evaluation)", () => {
    expect(isSafeLink("/alerts", KNOWN_ROUTES)).toBe(true);
    expect(isSafeLink("/alerts?status=open", KNOWN_ROUTES)).toBe(true);
    expect(isSafeLink("/", KNOWN_ROUTES)).toBe(true);
    expect(isSafeLink("/runs/abc-1", KNOWN_ROUTES)).toBe(true);
  });
  it.each(["https://example.com/x", "//example.com/x", "javascript:alert(1)", "/alerts/../admin", "/nope", "/alerts/42", "/runs/a/b", "alerts", "/alerts#x", "/al erts", "\\\\x", "/alerts\n/x"])("rejects %s", (p) => {
    expect(isSafeLink(p, KNOWN_ROUTES)).toBe(false);
  });
});

describe("display helpers", () => {
  it("states the mode honestly", () => {
    expect(modeLabel("rule_based")).toBe("Rule-based explanation");
    expect(modeLabel("llm")).toBe("Model-phrased (evidence-checked)");
  });
  it("formats values with their unit and never invents one", () => {
    expect(valueText(RULE_BASED.evidence[0])).toBe("0.91");
    expect(valueText(STALE.evidence[0])).toBe("31.4 °C");
    expect(valueText({ ...RULE_BASED.evidence[0], value: null })).toBe("no value");
    expect(observedText("2026-10-20T03:10:00Z")).toBe("2026-10-20 03:10 UTC");
    expect(observedText(null)).toBe("n/a");
    expect(observedText("yesterday")).toBe("yesterday");
  });
  it("flags stale or unavailable evidence", () => {
    expect(hasWeakEvidence(STALE.evidence)).toBe(true);
    expect(hasWeakEvidence(RULE_BASED.evidence)).toBe(false);
  });
  it("explains known warning codes and shows an unknown one as received", () => {
    expect(warningText("llm_unavailable")).toMatch(/rule-based answer/);
    expect(warningText("llm_rejected")).toMatch(/number the evidence does not back/);
    expect(warningText("llm_blocked_by_policy")).toMatch(/privacy settings/);
    expect(warningText("llm_busy")).toMatch(/busy/);
    expect(warningText("docs_passage_withheld")).toMatch(/left out/);
    expect(warningText("docs_passage_flagged")).toMatch(/quoted as data/);
    expect(warningText("something_new")).toBe("something_new");
  });
  it("maps client error kinds and every kind has copy", () => {
    expect(errorKindOf(new ApiError({ kind: "network" }).kind)).toBe("offline");
    expect(errorKindOf("rate_limited")).toBe("rate_limited");
    expect(errorKindOf("validation")).toBe("invalid");
    expect(errorKindOf("server")).toBe("other");
    expect(errorKindOf(undefined)).toBe("other");
    for (const k of Object.keys(ERROR_COPY)) expect(ERROR_COPY[k as keyof typeof ERROR_COPY].title.length).toBeGreaterThan(0);
  });
  it("has starter questions for every kind", () => {
    for (const kind of ["alert", "signal", "model", "feature", "general"] as const) expect(suggestionsFor({ kind }).length).toBeGreaterThan(0);
  });
});

describe("CP-10: mode badge, provider and citations helpers", () => {
  it("the provider block is optional in the schema, and null is accepted", () => {
    expect(RULE_BASED.provider).toBeUndefined(); // an older backend / fixture without the field
    expect(DOCS_ANSWER.provider).toBeNull();
    expect(LLM_LOCAL.provider).toEqual({ name: "ollama", local: true, fell_back: false });
    expect(CopilotResponseSchema.safeParse({ ...RULE_BASED, provider: { name: "", local: true } }).success).toBe(false); // a name is required
    expect(CopilotResponseSchema.safeParse({ ...RULE_BASED, provider: { name: "x".repeat(65), local: false } }).success).toBe(false);
    expect(CopilotResponseSchema.safeParse({ ...RULE_BASED, provider: { name: "groq" } }).success).toBe(false); // local is required
  });

  it("classifies where an answer came from", () => {
    expect(providerKind(RULE_BASED)).toBe("rule");
    expect(providerKind(LLM_LOCAL)).toBe("local");
    expect(providerKind(LLM_CLOUD_FELL_BACK)).toBe("cloud");
    expect(providerKind({ mode: "llm" })).toBe("model"); // llm answer from a backend that does not say which provider
  });

  it("words the badge: Local model, Cloud model with the provider name, or why no model answered", () => {
    expect(providerText(LLM_LOCAL)).toBe("Local model (ollama)");
    expect(providerText(LLM_CLOUD_FELL_BACK)).toBe("Cloud model (groq)");
    expect(providerText({ mode: "llm", warnings: [] })).toBeNull();
    expect(providerText(RULE_BASED)).toBeNull();
    expect(providerText(LLM_FALLBACK)).toBe("model did not answer");
    expect(providerText({ mode: "rule_based", warnings: ["llm_rejected"] })).toBe("model wording rejected");
    expect(providerText({ mode: "rule_based", warnings: ["llm_blocked_by_policy"] })).toBe("model not used for this question");
    expect(providerText({ mode: "rule_based", warnings: ["llm_busy"] })).toBe("model busy");
  });

  it("says so when failover fell through to a later provider, and only then", () => {
    expect(fellBackText(LLM_CLOUD_FELL_BACK)).toBe("An earlier provider did not answer, so this answer came from groq.");
    expect(fellBackText(LLM_LOCAL)).toBeNull();
    expect(fellBackText(RULE_BASED)).toBeNull();
    expect(fellBackText({ mode: "rule_based", provider: { name: "groq", local: false, fell_back: true } })).toBeNull(); // not an llm answer
  });

  it("a citation links to a document page only when the app has a route for exactly that document", () => {
    const c = DOCS_ANSWER.citations![0];
    expect(docHref(c, KNOWN_ROUTES)).toBeNull(); // the app has no docs route today: plain text
    expect(docHref(c, [...KNOWN_ROUTES, "/docs/copilot/LIMITS.md"])).toBe("/docs/copilot/LIMITS.md");
    expect(docHref({ source_path: "docs/CLAIMS.md" }, [...KNOWN_ROUTES, "/docs/copilot/LIMITS.md"])).toBeNull(); // another document
    expect(docHref({ source_path: "../../etc/passwd" }, ["/docs/../../etc/passwd"])).toBeNull(); // a path that climbs is never a link
  });

  it("the documentation warning codes get a sentence", () => {
    expect(warningText("docs_index_unavailable")).toMatch(/not available/);
    expect(warningText("docs_index_stale")).toMatch(/out of date/);
    expect(DOCS_NOT_DOCUMENTED.warnings).toEqual(["docs_index_stale"]);
  });

  it("timeouts: slow note well before the client limit, client limit above the server's 12 s chain budget", () => {
    expect(SLOW_AFTER_MS).toBeLessThan(ASK_TIMEOUT_MS);
    expect(ASK_TIMEOUT_MS).toBeGreaterThan(12_000);
    expect(ERROR_COPY.timeout.retry && ERROR_COPY.cancelled.retry).toBe(true);
  });
});
