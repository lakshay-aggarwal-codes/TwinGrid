/**
 * The activation link is `<base>/activate#token=...`. The fragment is never sent to a server, but it stays in the
 * address bar and history, so it is read once and removed from the URL immediately (history.replaceState).
 * The token is then held in memory only (this module), never in storage.
 */
let stashed: string | null = null;

/** Read `token` from location.hash, clear the hash, and remember it. With no hash, returns what was read earlier (or null). */
export function takeActivationToken(): string | null {
  const hash = window.location.hash;
  if (hash.length > 1) {
    const token = new URLSearchParams(hash.slice(1)).get('token');
    window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
    if (token) stashed = token;
  }
  return stashed;
}

/** Forget the token (after it has been used or rejected). */
export function forgetActivationToken(): void {
  stashed = null;
}
