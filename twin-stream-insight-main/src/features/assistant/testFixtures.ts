/** SYNTHETIC copilot responses (src/contract/fixtures-copilot/*.json): hand-written from section 8.4, not captured from a backend. */
import { CopilotResponseSchema } from "./schema";
import ruleBased from "../../contract/fixtures-copilot/rule_based.json";
import stale from "../../contract/fixtures-copilot/stale.json";
import unknownCause from "../../contract/fixtures-copilot/unknown_cause.json";
import refusal from "../../contract/fixtures-copilot/refusal.json";
import hostile from "../../contract/fixtures-copilot/hostile_text.json";
import llmFallback from "../../contract/fixtures-copilot/llm_fallback.json";
import llmLocal from "../../contract/fixtures-copilot/llm_local.json";
import llmCloudFellBack from "../../contract/fixtures-copilot/llm_cloud_fell_back.json";
import docsAnswer from "../../contract/fixtures-copilot/docs_answer.json";
import docsNotDocumented from "../../contract/fixtures-copilot/docs_not_documented.json";

export const RULE_BASED = CopilotResponseSchema.parse(ruleBased);
export const STALE = CopilotResponseSchema.parse(stale);
export const UNKNOWN_CAUSE = CopilotResponseSchema.parse(unknownCause);
export const REFUSAL = CopilotResponseSchema.parse(refusal);
export const HOSTILE = CopilotResponseSchema.parse(hostile);
export const LLM_FALLBACK = CopilotResponseSchema.parse(llmFallback);
export const LLM_LOCAL = CopilotResponseSchema.parse(llmLocal);
export const LLM_CLOUD_FELL_BACK = CopilotResponseSchema.parse(llmCloudFellBack);
export const DOCS_ANSWER = CopilotResponseSchema.parse(docsAnswer);
export const DOCS_NOT_DOCUMENTED = CopilotResponseSchema.parse(docsNotDocumented);
export const KNOWN_ROUTES = ["/", "/analytics", "/runs", "/alerts", "/replay"] as const;
