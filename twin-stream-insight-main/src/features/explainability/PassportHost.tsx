import { useSyncExternalStore } from "react";
import { ModelPassportButton } from "./ModelPassportButton";
import { PassportDrawer } from "./PassportDrawer";
import { closePassport, getPassportState, subscribePassport } from "./passportStore";

/**
 * Slot `header-actions`: the one global "Model passport" button and the one drawer every other button, command and
 * link opens. The drawer's query runs only while it is open.
 */
export default function PassportHost() {
  const s = useSyncExternalStore(subscribePassport, getPassportState, getPassportState);
  return (
    <>
      <ModelPassportButton />
      <PassportDrawer open={s.open} kind={s.kind} onClose={closePassport} />
    </>
  );
}
