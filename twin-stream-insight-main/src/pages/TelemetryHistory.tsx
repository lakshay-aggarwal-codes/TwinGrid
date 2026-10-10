import { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePageTitle } from '@/hooks/usePageTitle';
import { isTelemetryHistoryEnabled } from '@/telemetry/history/flag';
import { MEASURANDS } from '@/telemetry/history/model';
import { TelemetryHistoryScreen } from '@/components/charts/TelemetryHistoryScreen';

/** `/telemetry`: stored telemetry history (BC-12). Historical samples only; the live value stays on the live twin. */
const TelemetryHistory = () => {
  usePageTitle('TwinGrid — Telemetry history');
  const enabled = isTelemetryHistoryEnabled();
  const [measurand, setMeasurand] = useState<string>(MEASURANDS[3].id);
  const [hours, setHours] = useState(24);
  // The REQUESTED window ends when the person opened the page / changed the window / pressed refresh. Not data time.
  const [windowEndMs, setWindowEndMs] = useState(() => Date.now());

  return (
    <main className="mx-auto h-full w-full max-w-5xl space-y-4 overflow-y-auto p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-foreground">Telemetry history</h1>
        <Link to="/" className="text-xs text-primary underline">
          Back to live twin
        </Link>
      </header>
      <p className="text-xs text-muted-foreground">
        Stored samples from the telemetry store, with each sample&apos;s origin and quality. This is history, not the live value, and it does not control a facility.
      </p>
      {enabled ? (
        <TelemetryHistoryScreen
          measurand={measurand}
          hours={hours}
          windowEndMs={windowEndMs}
          onMeasurandChange={setMeasurand}
          onHoursChange={(h) => {
            setHours(h);
            setWindowEndMs(Date.now());
          }}
          onRefreshWindow={() => setWindowEndMs(Date.now())}
        />
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="telemetry-history-disabled">
          The telemetry history view is turned off in this build.
        </p>
      )}
    </main>
  );
};

export default TelemetryHistory;
