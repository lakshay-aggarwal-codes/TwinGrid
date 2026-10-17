import { useState } from "react";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useRole } from "@/hooks/useAuth";
import { CreateOrderForm } from "./CreateOrderForm";
import { HealthPanel } from "./HealthPanel";
import { ModelContext } from "./ModelContext";
import { EMPTY_FORM, formFromHealth, type CreateForm } from "./model";
import type { HealthAsset } from "./schema";
import { WorkOrdersPanel } from "./WorkOrdersPanel";

/**
 * `/maintenance`: per-asset health and trend (a rule on simulated data, no remaining-life figure), and work orders that
 * an operator can raise by hand, from an alert, or from a health warning, then move open -> in progress -> done.
 */
export default function MaintenancePage() {
  usePageTitle("Maintenance");
  const { isOperator } = useRole();
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);

  const fromHealth = (asset: HealthAsset) => {
    setForm(formFromHealth(asset));
    // Bring the prefilled form into view for keyboard and screen-reader users.
    queueMicrotask(() => document.getElementById("mx-new")?.scrollIntoView?.({ block: "nearest" }));
  };

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-4" data-testid="maintenance-page">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">Maintenance</h1>
        <p className="text-sm text-muted-foreground">
          Asset health from stored simulated telemetry, and work orders to follow up on it. No remaining-life estimate is shown because no validated model applies.
        </p>
      </header>
      <HealthPanel canCreate={isOperator} onCreate={fromHealth} />
      <CreateOrderForm form={form} onChange={setForm} canCreate={isOperator} />
      <WorkOrdersPanel canWrite={isOperator} />
      <ModelContext />
    </main>
  );
}
