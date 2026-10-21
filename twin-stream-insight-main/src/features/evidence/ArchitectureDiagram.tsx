import { BOUNDARIES, SOURCES } from "./data";

interface BoxProps {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  lines: readonly string[];
  dashed?: boolean;
}

function Box({ x, y, w, h, title, lines, dashed = false }: BoxProps) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={8} className="fill-card stroke-border" strokeWidth={1.5} strokeDasharray={dashed ? "6 4" : undefined} />
      <text x={x + 12} y={y + 22} className="fill-foreground" fontSize={13} fontWeight={600}>
        {title}
      </text>
      {lines.map((l, i) => (
        <text key={l} x={x + 12} y={y + 42 + i * 16} className="fill-muted-foreground" fontSize={11}>
          {l}
        </text>
      ))}
    </g>
  );
}

function Arrow({ x1, y1, x2, y2, label, lx, ly }: { x1: number; y1: number; x2: number; y2: number; label?: string; lx?: number; ly?: number }) {
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeWidth={1.5} markerEnd="url(#evidence-arrow)" />
      {label && (
        <text x={lx} y={ly} textAnchor="middle" className="fill-muted-foreground" fontSize={10}>
          {label}
        </text>
      )}
    </g>
  );
}

/**
 * The boundaries described in docs/architecture/system.md, drawn by hand (no layout library). It shows what talks to
 * what, and, dashed, what is not built. It does not show every module.
 */
export function ArchitectureDiagram() {
  return (
    <figure className="space-y-3" data-testid="architecture">
      <svg viewBox="0 0 760 380" role="img" aria-labelledby="arch-title arch-desc" className="h-auto w-full text-muted-foreground">
        <title id="arch-title">TwinGrid architecture boundaries</title>
        <desc id="arch-desc">
          The browser talks to the FastAPI backend over REST and a WebSocket. The backend uses the simulator and models and stores data in Postgres, Redis and model files. A worker runs queued jobs on the simulator. A real facility is
          not connected.
        </desc>
        <defs>
          <marker id="evidence-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
          </marker>
        </defs>

        <Box x={10} y={20} w={200} h={80} title="Browser" lines={["React, Vite, Three.js", "twin-stream-insight-main"]} />
        <Box x={280} y={20} w={220} h={120} title="FastAPI backend (api/)" lines={["middleware, routes, plugins", "services, repositories", "supervisor: live broadcast loop"]} />
        <Box x={560} y={20} w={190} h={120} title="Simulator + models (src/)" lines={["physics simulator", "RL environment", "anomaly detector, forecaster", "artifact gate"]} />
        <Box x={280} y={230} w={220} h={80} title="Storage" lines={["Postgres, Redis (job queue)", "models/ registry and files"]} />
        <Box x={560} y={230} w={190} h={80} title="RQ worker" lines={["queued jobs", "run on the same simulator"]} />
        <Box x={10} y={230} w={200} h={80} title="Real facility" lines={["not connected", "no BACnet, Modbus or SNMP"]} dashed />

        <Arrow x1={210} y1={60} x2={280} y2={60} label="REST, WS" lx={245} ly={48} />
        <Arrow x1={500} y1={80} x2={560} y2={80} label="calls" lx={530} ly={68} />
        <Arrow x1={390} y1={140} x2={390} y2={230} label="reads, writes" lx={425} ly={190} />
        <Arrow x1={560} y1={270} x2={500} y2={270} label="jobs" lx={530} ly={258} />
        <Arrow x1={655} y1={230} x2={655} y2={140} label="simulates" lx={690} ly={190} />
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        Simplified from <code>{SOURCES.architecture}</code>. The dashed box is something the repository does not do.
      </figcaption>
      <ul className="grid gap-2 text-sm md:grid-cols-2" aria-label="What each box is">
        {BOUNDARIES.map((b) => (
          <li key={b.name} className="rounded-md border border-border bg-card p-3">
            <span className="font-medium text-foreground">{b.name}.</span> <span className="text-muted-foreground">{b.detail}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
