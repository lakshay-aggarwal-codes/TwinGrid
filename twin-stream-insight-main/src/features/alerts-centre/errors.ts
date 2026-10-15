import { isApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";

/** Plain-language text for a failed alert change. Chosen from the error KIND only; backend text never reaches the page. */
export function changeErrorText(e: unknown): string {
  if (e instanceof AuthRequiredError) return "Your session has ended. Sign in again to change alerts.";
  if (!isApiError(e)) return "The change could not be saved. Try again.";
  switch (e.kind) {
    case "forbidden":
      return "Only operators can change alerts.";
    case "conflict":
      return "That change is no longer possible: the alert was changed by someone else. Reload to see its current state.";
    case "not_found":
      return "This alert no longer exists.";
    case "validation":
      return "Not accepted. The assignee must be an existing operator, and a note cannot be empty.";
    case "rate_limited":
      return e.retryAfterS ? `Too many changes. Try again in ${e.retryAfterS} seconds.` : "Too many changes. Try again shortly.";
    default:
      return "The change could not be saved. Try again.";
  }
}
