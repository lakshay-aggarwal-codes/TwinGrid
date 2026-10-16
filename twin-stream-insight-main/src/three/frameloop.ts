/**
 * Task 23: the 3D scene renders on demand while the tab is visible and not at all while it is hidden (no GPU work for a
 * tab nobody can see). Feed frames keep arriving meanwhile; the scene simply draws the newest one when the tab returns.
 */
export type SceneFrameloop = "demand" | "never";

export const sceneFrameloop = (tabVisible: boolean): SceneFrameloop => (tabVisible ? "demand" : "never");
