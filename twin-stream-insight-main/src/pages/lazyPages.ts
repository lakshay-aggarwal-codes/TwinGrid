/**
 * Stage 17: the loader for the lazily-loaded legacy page lives here so the
 * router (React.lazy) and the link (prefetch on hover/focus/touch) share the
 * same import() -- the browser fetches the chunk once, whichever runs first.
 */
export const loadLegacyPage = () => import("./Index");
