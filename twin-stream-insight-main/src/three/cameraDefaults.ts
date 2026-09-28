/** Camera framing used both as TwinScene's initial view and as the target of
 * Stage 12's "focus on facility" tween (see useCameraFocus.focusOnOverview) --
 * kept in one place, alongside the Canvas/OrbitControls props that define
 * this same framing in TwinScene, so the two can't drift apart. Split into
 * its own module (rather than living in TwinScene.tsx) so useCameraFocus can
 * import it without a circular TwinScene <-> useCameraFocus dependency. */
export const DEFAULT_CAMERA_POSITION: [number, number, number] = [16, 14, 22];
export const DEFAULT_CAMERA_TARGET: [number, number, number] = [11, 0, 0];
