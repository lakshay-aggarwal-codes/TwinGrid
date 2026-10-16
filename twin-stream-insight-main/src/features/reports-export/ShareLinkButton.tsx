import { useState } from "react";
import { Link2 } from "lucide-react";
import { shareUrl } from "./shareLink";

const BTN =
  "inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Copies the current page address (credential-like query parameters and the #fragment removed) to the clipboard. */
export function ShareLinkButton({ href, label = "Copy link" }: { href?: string; label?: string }) {
  const [message, setMessage] = useState("");
  const copy = async () => {
    const url = shareUrl(href ?? window.location.href);
    if (!url) return setMessage("This page has no link that can be shared.");
    try {
      await navigator.clipboard.writeText(url);
      setMessage("Link copied.");
    } catch {
      setMessage("Could not copy. Copy the address bar instead.");
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" className={BTN} onClick={() => void copy()}>
        <Link2 className="h-3.5 w-3.5" aria-hidden="true" /> {label}
      </button>
      <span role="status" aria-live="polite" className="sr-only">{message}</span>
    </span>
  );
}
