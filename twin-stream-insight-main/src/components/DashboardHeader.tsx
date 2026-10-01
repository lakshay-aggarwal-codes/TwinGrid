import { useState, useEffect } from "react";
import { Activity, Boxes } from "lucide-react";
import { RotateLink } from "@/components/transition/RotateLink";
import { Badge } from "@/components/ui/badge";

export function DashboardHeader() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <div
        role="status"
        data-testid="simulated-banner"
        className="shrink-0 border-b border-warning/40 bg-warning/10 px-6 py-1 text-center text-[11px] font-medium uppercase tracking-wider text-warning"
      >
        SIMULATED — no measured telemetry
      </div>
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-card/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-md bg-primary/20 flex items-center justify-center">
          <Activity className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          TwinGrid —{" "}
          <span className="text-primary glow-text">Analytics</span>{" "}
        </h1>
      </div>
      <div className="flex items-center gap-4">
        <RotateLink
          to="/"
          direction={-1}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <Boxes className="h-3.5 w-3.5" />
          Live Twin
        </RotateLink>
        <span className="font-mono text-sm text-muted-foreground">
          {time.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "numeric",
          })}{" "}
          <span className="text-foreground">{time.toLocaleTimeString()}</span>
        </span>
        <Badge
          variant="outline"
          className="border-success/50 text-success gap-1.5"
        >
          <span className="h-2 w-2 rounded-full bg-success pulse-dot inline-block" />
          Systems Online
        </Badge>
      </div>
    </header>
    </>
  );
}
