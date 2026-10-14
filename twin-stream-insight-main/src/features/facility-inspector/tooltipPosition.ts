/** Task 13: where the hover tooltip goes. Pure, so it can be tested without a DOM. */
const OFFSET = 14;
const EDGE = 8;

/** Below-right of a pointer at (x, y), kept inside the viewport (flipped above it near the bottom edge). */
export function tooltipPosition(x: number, y: number, box: { width: number; height: number }, viewport: { width: number; height: number }): { left: number; top: number } {
  const left = Math.max(EDGE, Math.min(x + OFFSET, viewport.width - box.width - EDGE));
  const flipped = y + OFFSET + box.height > viewport.height - EDGE;
  const top = Math.max(EDGE, flipped ? y - OFFSET - box.height : y + OFFSET);
  return { left, top };
}
