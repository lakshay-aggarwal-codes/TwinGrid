import type { AlertRecord } from '@/api/apiClient';
import { AlertRowItem, type Role } from './AlertRowItem';
import { groupByEpisode } from './alertModel';

interface AlertListProps {
  alerts: readonly AlertRecord[];
  role: Role;
  queryKey: readonly unknown[];
  onSelect: (alert: AlertRecord) => void;
}

/** Rows grouped by backend `dedupe_key` for display ("episode, n detections"). Every row is rendered; none is hidden. */
export function AlertList({ alerts, role, queryKey, onSelect }: AlertListProps) {
  const groups = groupByEpisode(alerts);
  return (
    <ul className="space-y-1.5" aria-label="Alerts">
      {groups.map((g) =>
        g.key !== null && g.rows.length > 1 ? (
          <li key={`episode-${g.key}`} data-episode={g.key} className="rounded-md border border-dashed border-border p-1.5 space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground" data-testid="episode-header">
              Episode · {g.rows.length} detections
            </p>
            <ul className="space-y-1.5">
              {g.rows.map((a) => (
                <AlertRowItem key={a.id} alert={a} role={role} queryKey={queryKey} onSelect={onSelect} />
              ))}
            </ul>
          </li>
        ) : (
          <AlertRowItem key={g.rows[0].id} alert={g.rows[0]} role={role} queryKey={queryKey} onSelect={onSelect} />
        ),
      )}
    </ul>
  );
}
