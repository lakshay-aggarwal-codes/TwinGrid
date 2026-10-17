import { AuthRequiredError } from "@/authClient";
import { isApiError } from "@/api/apiError";

/** Text for a failed write. Never the server's message: only the error kind selects the wording. */
export function writeErrorText(e: unknown): string {
  if (e instanceof AuthRequiredError) return "Your session has ended. Sign in again to change work orders.";
  if (!isApiError(e)) return "The change could not be saved. Try again.";
  switch (e.kind) {
    case "forbidden":
      return "Only operators can create or change work orders.";
    case "not_found":
      return "That alert, asset or work order no longer exists.";
    case "conflict":
      return "That change is no longer possible: the work order was changed or is already closed. Reload to see its state.";
    case "validation":
      return "Not accepted. Check the fields and try again.";
    case "rate_limited":
      return e.retryAfterS ? `Too many changes. Try again in ${e.retryAfterS} seconds.` : "Too many changes. Try again shortly.";
    default:
      return "The change could not be saved. Try again.";
  }
}
