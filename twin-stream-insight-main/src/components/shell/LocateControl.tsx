import { useId } from "react";
import { MapPin } from "lucide-react";
import { listRacksByZone } from "@/three/facilityLayout";

interface LocateControlProps {
  onLocate: (rackId: string) => void;
}

/** "row-2" -> "Row 2" */
function formatRow(rowId: string): string {
  const n = rowId.split("-")[1];
  return `Row ${n}`;
}

/** "zone-1-row-2-rack-3" -> "Rack 3" */
function formatRackNumber(rackId: string): string {
  const n = rackId.split("-rack-")[1];
  return `Rack ${n}`;
}

/**
 * Locate any rack by ID and focus the camera on it (Stage 4). The
 * identity/coordinate model and the focus/camera-tween mechanism this uses
 * already exist from Stages 1-3. A richer search/command palette across
 * racks, zones, sensors and alerts is Stage 11's job, not this one's.
 */
export function LocateControl({ onLocate }: LocateControlProps) {
  const selectId = useId();
  const groups = listRacksByZone();

  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const rackId = event.target.value;
    if (!rackId) return;
    onLocate(rackId);
    // Reset to the placeholder so choosing the same rack again still fires
    // onChange (and so re-focusing it triggers a fresh camera tween).
    event.target.value = "";
  };

  return (
    <div className="flex items-center gap-1.5">
      <MapPin className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      <label htmlFor={selectId} className="sr-only">
        Locate a rack
      </label>
      <select
        id={selectId}
        defaultValue=""
        onChange={handleChange}
        className="bg-transparent text-sm text-muted-foreground hover:text-foreground border border-border rounded-md px-2 py-1 outline-none focus:border-primary focus:text-foreground transition-colors max-w-[220px]"
      >
        <option value="" disabled>
          Locate a rack…
        </option>
        {groups.map((group) => (
          <optgroup key={group.zoneId} label={group.zoneLabel}>
            {group.racks.map((rack) => (
              <option key={rack.rackId} value={rack.rackId}>
                {formatRow(rack.rowId)} · {formatRackNumber(rack.rackId)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
