/**
 * Task 22: a link that is safe to paste into chat or email. The page's own view state (query string such as the alert id,
 * what-if inputs, replay position) is kept; anything that looks like a credential, and the whole #fragment, is dropped.
 */
const SENSITIVE = /^(token|access_token|id_token|refresh_token|ticket|ws_ticket|password|passwd|secret|key|api_key|apikey|auth|authorization|session|sid|jwt|code)$/i;

export function shareUrl(href: string): string {
  let u: URL;
  try {
    u = new URL(href);
  } catch {
    return "";
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return "";
  u.username = "";
  u.password = "";
  u.hash = "";
  for (const k of [...u.searchParams.keys()]) if (SENSITIVE.test(k)) u.searchParams.delete(k);
  return u.toString();
}
