import { useEffect, useRef, useState } from "react";
import { BellRing } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "@/components/ui/sonner";
import { countAlerts, scanForNewCritical, type InboxAlert } from "./model";
import { playAlertTone, readSoundPref } from "./prefs";
import { useInbox } from "./useInbox";

const MAX_TOASTS = 3;

/**
 * Header widget (slot `header-actions`, every role): a link to the alerts centre with the number of OPEN critical alerts
 * as text, plus the app-wide notifier. A critical alert that appears after the first load raises a toast, is announced
 * in a polite live region, and (only if the user turned sound on) plays a short tone. The alerts that already exist when
 * the app opens are counted but never announced.
 */
export default function AlertWatcher() {
  const { query } = useInbox();
  const navigate = useNavigate();
  const seen = useRef<Set<number> | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const data: InboxAlert[] | undefined = query.data;

  useEffect(() => {
    if (!data) return;
    const scan = scanForNewCritical(seen.current, data);
    seen.current = scan.seen;
    if (scan.fresh.length === 0) return;
    scan.fresh.slice(0, MAX_TOASTS).forEach((a) => {
      toast.error(`Critical alert #${a.id}`, {
        description: a.message,
        duration: 10_000,
        action: { label: "Open", onClick: () => navigate(`/alerts?alert=${a.id}`) },
      });
    });
    if (scan.fresh.length > MAX_TOASTS) toast.error(`${scan.fresh.length - MAX_TOASTS} more new critical alerts`, { duration: 10_000, action: { label: "Open", onClick: () => navigate("/alerts") } });
    setAnnouncement(scan.fresh.length === 1 ? `New critical alert: ${scan.fresh[0].message}` : `${scan.fresh.length} new critical alerts`);
    if (readSoundPref()) playAlertTone();
  }, [data, navigate]);

  const openCritical = data ? countAlerts(data).openCritical : null;
  const label = openCritical === null ? "Alerts" : `Alerts, ${openCritical} open critical`;
  return (
    <>
      <Link
        to="/alerts"
        aria-label={label}
        data-testid="alert-watcher-link"
        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <BellRing aria-hidden="true" className="h-3.5 w-3.5" />
        <span aria-hidden="true">{openCritical === null ? "Alerts" : `Alerts · ${openCritical} critical`}</span>
      </Link>
      <span role="status" aria-live="polite" data-testid="alert-announcer" className="sr-only">
        {announcement}
      </span>
    </>
  );
}
