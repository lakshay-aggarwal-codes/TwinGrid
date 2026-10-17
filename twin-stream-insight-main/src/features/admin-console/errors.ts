import { isApiError } from "@/api/apiError";
import { AuthRequiredError } from "@/authClient";

/** Text for a failed admin action. Never the server's message: only the error kind selects the wording. */
export function actionErrorText(e: unknown, what: string): string {
  if (e instanceof AuthRequiredError) return `Your session has ended. Sign in again to ${what}.`;
  if (!isApiError(e)) return `Could not ${what}. Try again.`;
  switch (e.kind) {
    case "forbidden":
      return `Only admins can ${what}.`;
    case "not_found":
      return "That no longer exists. Reload to see the current list.";
    case "conflict":
      return "That change is not possible right now (for example, it is your own account, nothing would change, or it already exists).";
    case "validation":
      return "Not accepted. Check the value and try again. Webhook URLs must be https and public.";
    case "rate_limited":
      return e.retryAfterS ? `Too many requests. Try again in ${e.retryAfterS} seconds.` : "Too many requests. Try again shortly.";
    default:
      return `Could not ${what}. Try again.`;
  }
}
