import { describe, expect, it } from 'vitest';

import { CANVAS_MIN_HEIGHT, computeCanvasHeight } from '../canvasHeight';

/**
 * The topology canvas was a hardcoded 500px. It filled the width but never the
 * height, so on a tall monitor the bottom half of the page was empty while the
 * diagram sat squeezed into a strip — reported by a user, with a screenshot
 * showing roughly half the viewport unused.
 *
 * These assert the arithmetic rather than the rendered box: jsdom reports zero
 * for every layout measurement, so a test that rendered the component and read
 * its height would pass against any implementation.
 */
describe('computeCanvasHeight', () => {
  it('fills the viewport below wherever the canvas starts', () => {
    // A 1400px-tall window with the canvas top at 300px leaves 1100px, less the
    // breathing room below.
    expect(
      computeCanvasHeight({ top: 300, viewportHeight: 1400, bottomGap: 24 })
    ).toBe(1076);
  });

  it('grows when the window does — this is the whole point', () => {
    const short = computeCanvasHeight({ top: 300, viewportHeight: 900, bottomGap: 24 });
    const tall = computeCanvasHeight({ top: 300, viewportHeight: 1600, bottomGap: 24 });
    expect(tall).toBeGreaterThan(short);
    expect(tall - short).toBe(700);
  });

  it('shrinks when the canvas starts lower down the page', () => {
    // The environment page carries more chrome above the canvas than the system
    // page does, so the same window yields a shorter canvas. Measuring the real
    // offset is what makes one component correct on both.
    const high = computeCanvasHeight({ top: 250, viewportHeight: 1200, bottomGap: 24 });
    const low = computeCanvasHeight({ top: 400, viewportHeight: 1200, bottomGap: 24 });
    expect(high - low).toBe(150);
  });

  it('never goes below the floor, however short the window', () => {
    // A laptop in a small window must not squash the diagram to nothing; the
    // page scrolls instead.
    expect(
      computeCanvasHeight({ top: 600, viewportHeight: 700, bottomGap: 24 })
    ).toBe(CANVAS_MIN_HEIGHT);
    expect(
      computeCanvasHeight({ top: 900, viewportHeight: 400, bottomGap: 24 })
    ).toBe(CANVAS_MIN_HEIGHT);
  });

  it('floors to a whole number of pixels', () => {
    // getBoundingClientRect returns fractional values on scaled displays, and a
    // fractional height feeds a sub-pixel container to React Flow.
    expect(
      computeCanvasHeight({ top: 300.6, viewportHeight: 1400.2, bottomGap: 24 })
    ).toBe(1075);
  });
});
