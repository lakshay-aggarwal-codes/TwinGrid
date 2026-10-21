/**
 * The visitor's request ticket {ref, token}, kept in sessionStorage so /access/pending survives a reload.
 * Storage may be unavailable (private mode, blocked): every access is wrapped, and the page then simply has no ticket.
 */
export interface AccessTicket {
  ref: string;
  token: string;
}

export const TICKET_KEY = 'twingrid.access-request';

export function saveTicket(ticket: AccessTicket): void {
  try {
    sessionStorage.setItem(TICKET_KEY, JSON.stringify({ ref: ticket.ref, token: ticket.token }));
  } catch {
    // storage unavailable: the ticket lives only in this page's memory (see usePendingTicket)
  }
}

export function loadTicket(): AccessTicket | null {
  try {
    const raw = sessionStorage.getItem(TICKET_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { ref?: unknown; token?: unknown };
    if (typeof parsed.ref === 'string' && parsed.ref && typeof parsed.token === 'string' && parsed.token) {
      return { ref: parsed.ref, token: parsed.token };
    }
  } catch {
    // corrupt or unreadable: behave as "no ticket"
  }
  return null;
}

export function clearTicket(): void {
  try {
    sessionStorage.removeItem(TICKET_KEY);
  } catch {
    // nothing to do
  }
}

/** Go to an in-app path without a reload. react-router's BrowserRouter listens to popstate, so this re-renders its routes. */
export function navigateTo(path: string): void {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
