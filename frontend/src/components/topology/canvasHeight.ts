/**
 * Sizing for the topology canvas.
 *
 * The canvas used to be a hardcoded 500px. It stretched to the width of the
 * screen but never the height, so on a tall monitor the diagram sat in a strip
 * with the bottom half of the page empty. The fix measures where the canvas
 * actually starts and gives it the rest of the viewport.
 *
 * Measuring beats a `calc(100vh - Npx)` rule because the two pages that mount
 * this component carry different chrome above it — the system page has a header
 * and tabs, the environment page has more — so any single constant is wrong on
 * one of them, and wrong again the moment either page gains a row.
 */

/** Never squash the diagram below this, however short the window. */
export const CANVAS_MIN_HEIGHT = 400;

/** Breathing room between the bottom of the canvas and the bottom of the window. */
export const CANVAS_BOTTOM_GAP = 24;

export interface CanvasHeightInput {
  /** The canvas's distance from the top of the viewport, from getBoundingClientRect. */
  top: number;
  viewportHeight: number;
  bottomGap: number;
}

export function computeCanvasHeight({
  top,
  viewportHeight,
  bottomGap,
}: CanvasHeightInput): number {
  const available = viewportHeight - top - bottomGap;
  // Floor rather than round: getBoundingClientRect returns fractional values on
  // scaled displays, and a fractional height hands React Flow a sub-pixel
  // container.
  return Math.max(CANVAS_MIN_HEIGHT, Math.floor(available));
}
