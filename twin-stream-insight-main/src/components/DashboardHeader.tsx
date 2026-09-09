import { useState, useEffect } from 'react';
import { Activity } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export function DashboardHeader() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-card/80 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-md bg-primary/20 flex items-center justify-center">
          <Activity className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          Digital Twin — <span className="text-primary glow-text">DC Conservation</span>
        </h1>
      </div>
      <div className="flex items-center gap-4">
        <span className="font-mono text-sm text-muted-foreground">
          {time.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}
          {' '}
          <span className="text-foreground">{time.toLocaleTimeString()}</span>
        </span>
        <Badge variant="outline" className="border-success/50 text-success gap-1.5">
          <span className="h-2 w-2 rounded-full bg-success pulse-dot inline-block" />
          Systems Online
        </Badge>
      </div>
    </header>
  );
}
