/** SYNTHETIC copilot responses (src/contract/fixtures-copilot/*.json): hand-written from section 8.4, not captured from a backend. */
import { CopilotResponseSchema } from "./schema";
import ruleBased from "../../contract/fixtures-copilot/rule_based.json";
import stale from "../../contract/fixtures-copilot/stale.json";
import unknownCause from "../../contract/fixtures-copilot/unknown_cause.json";
import refusal from "../../contract/fixtures-copilot/refusal.json";
import hostile from "../../contract/fixtures-copilot/hostile_text.json";
import llmFallback from "../../contract/fixtures-copilot/llm_fallback.json";

export const RULE_BASED = CopilotResponseSchema.parse(ruleBased);
export const STALE = CopilotResponseSchema.parse(stale);
export const UNKNOWN_CAUSE = CopilotResponseSchema.parse(unknownCause);
export const REFUSAL = CopilotResponseSchema.parse(refusal);
export const HOSTILE = CopilotResponseSchema.parse(hostile);
export const LLM_FALLBACK = CopilotResponseSchema.parse(llmFallback);
export const KNOWN_ROUTES = ["/", "/analytics", "/runs", "/alerts", "/replay"] as const;
