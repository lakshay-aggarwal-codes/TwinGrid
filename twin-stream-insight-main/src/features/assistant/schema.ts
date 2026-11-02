/**
 * Task 15: the Copilot v1 contract (playbook section 8.4) as runtime schemas. A response that does not match is a
 * "contract" error, never repaired: an unknown `source`, `origin`, `freshness` or `mode` is not guessed at.
 */
import { z } from "zod";

export const CONTEXT_KINDS = ["alert", "signal", "model", "feature", "general"] as const;
export type ContextKind = (typeof CONTEXT_KINDS)[number];

export const EVIDENCE_SOURCES = ["alert_explanation", "twin_state", "threshold_rule", "model_passport", "claims_ledger", "capability_catalogue", "doc_passage"] as const;
export const ORIGINS = ["simulated", "measured", "replayed", "assumed", "documentation", "unknown"] as const;
export const FRESHNESS = ["fresh", "stale", "unavailable", "static"] as const;
export const MODES = ["rule_based", "llm"] as const;

export type Origin = (typeof ORIGINS)[number];
export type Freshness = (typeof FRESHNESS)[number];
export type Mode = (typeof MODES)[number];

export const EvidenceSchema = z
  .object({
    id: z.string().regex(/^E\d{1,3}$/),
    source: z.enum(EVIDENCE_SOURCES),
    entity: z.string().max(200),
    field: z.string().max(100),
    value: z.union([z.number(), z.string(), z.boolean(), z.null()]),
    unit: z.string().max(40).nullable(),
    observed_at: z.string().max(40).nullable(),
    origin: z.enum(ORIGINS),
    freshness: z.enum(FRESHNESS),
  })
  .passthrough();
export type Evidence = z.output<typeof EvidenceSchema>;

export const LinkSchema = z.object({ label: z.string().min(1).max(120), path: z.string().min(1).max(200) }).passthrough();
export type AnswerLink = z.output<typeof LinkSchema>;

/** CP-7: where a documentation passage in the answer came from; `evidence_id` names its `doc_passage` evidence item. */
export const CitationSchema = z
  .object({
    evidence_id: z.string().regex(/^E\d{1,3}$/),
    source_path: z.string().min(1).max(200),
    heading_path: z.string().max(300),
    chunk_id: z.string().min(1).max(200),
    score: z.number(),
    matched_terms: z.array(z.string().max(60)).max(20),
  })
  .passthrough();
export type Citation = z.output<typeof CitationSchema>;

/** CP-10: which provider phrased an `llm` answer. Name and data policy only; `fell_back` = an earlier provider was tried or skipped first. */
export const ProviderSchema = z
  .object({
    name: z.string().min(1).max(64),
    local: z.boolean(),
    fell_back: z.boolean().optional(),
  })
  .passthrough();
export type ProviderInfo = z.output<typeof ProviderSchema>;

export const CopilotResponseSchema = z
  .object({
    request_id: z.string().max(100),
    mode: z.enum(MODES),
    answer: z.string().max(1500),
    evidence: z.array(EvidenceSchema).max(50),
    unknowns: z.array(z.string().max(500)).max(20),
    warnings: z.array(z.string().max(200)).max(20),
    links: z.array(LinkSchema).max(10),
    limits: z.object({ provider_configured: z.boolean() }).passthrough(),
    citations: z.array(CitationSchema).max(10).optional(), // CP-7; absent in responses from an older backend
    provider: ProviderSchema.nullable().optional(), // CP-10; null or absent for a rule-based answer or an older backend
  })
  .passthrough();
export type CopilotResponse = z.output<typeof CopilotResponseSchema>;

export interface ContextRef {
  readonly kind: ContextKind;
  readonly id?: string;
}
export interface HistoryItem {
  readonly role: "user" | "assistant";
  readonly text: string;
}
export interface AskBody {
  question: string;
  context: { kind: ContextKind; id?: string };
  history: HistoryItem[];
}
