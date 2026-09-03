import { describe, expect, it } from 'vitest';
import { createAppTheme, edgeLabelStyle, thirdPartySurfaceStyles } from '../theme';

/**
 * FullCalendar and React Flow ship stylesheets that hardcode a light surface.
 * Neither knows about the MUI palette, so in dark mode their surfaces stayed
 * white while the text on them inherited the theme's white — rendering their
 * own labels at a contrast ratio of 1.00, i.e. invisible. These tests pin the
 * contrast, not the colour: a future palette change is free to move the hues,
 * but may not make a label unreadable again.
 */

// --- WCAG relative luminance / contrast, over the small subset of CSS colour
// syntaxes the MUI palette actually emits (#rgb, #rrggbb, rgb(), rgba()).
function parse(colour: string): { r: number; g: number; b: number; a: number } {
  const hex = colour.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (c) => c + c) : hex[1];
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 };
  }
  const rgb = colour.match(/rgba?\(([^)]+)\)/);
  if (!rgb) throw new Error(`unsupported colour: ${colour}`);
  const p = rgb[1].split(',').map((s) => parseFloat(s));
  return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
}

function luminance(c: { r: number; g: number; b: number }): number {
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}

/** Contrast of `fg` composited over the opaque `bg`. */
function contrast(fg: string, bg: string): number {
  const f = parse(fg);
  const b = parse(bg);
  const flat = {
    r: f.r * f.a + b.r * (1 - f.a),
    g: f.g * f.a + b.g * (1 - f.a),
    b: f.b * f.a + b.b * (1 - f.a),
  };
  const l1 = luminance(flat);
  const l2 = luminance(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

describe('contrast helper', () => {
  it('reports the invisible case as 1 and black-on-white as 21', () => {
    expect(contrast('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 0);
  });
});

describe('FullCalendar surfaces follow the palette', () => {
  it.each(['light', 'dark'] as const)('%s: weekday headings are readable on the sticky header', (mode) => {
    const theme = createAppTheme(mode);
    const styles = thirdPartySurfaceStyles(theme);

    // FullCalendar paints the sticky header row with --fc-page-bg-color and lets
    // the text inherit. Left at its own default (#fff) that is white on white.
    const pageBg = styles['.fc.fc']['--fc-page-bg-color'];
    expect(pageBg).toBe(theme.palette.background.paper);
    expect(contrast(theme.palette.text.primary, pageBg)).toBeGreaterThanOrEqual(4.5);
  });

  it('dark mode does not leave the calendar surface white', () => {
    const styles = thirdPartySurfaceStyles(createAppTheme('dark'));
    expect(styles['.fc.fc']['--fc-page-bg-color'].toLowerCase()).not.toMatch(/^#fff/);
  });
});

describe('React Flow surfaces follow the palette', () => {
  it('the minimap panel is not a white block in dark mode', () => {
    const theme = createAppTheme('dark');
    const styles = thirdPartySurfaceStyles(theme);
    expect(styles['.react-flow__minimap.react-flow__minimap'].backgroundColor).toBe(theme.palette.background.paper);
  });

  it('the attribution link is readable rather than grey-on-white', () => {
    const theme = createAppTheme('dark');
    const styles = thirdPartySurfaceStyles(theme);
    const link = styles['.react-flow__attribution.react-flow__attribution a'].color;
    expect(contrast(link, theme.palette.background.default)).toBeGreaterThanOrEqual(3);
  });
});

describe('the overrides can actually win the cascade', () => {
  // Both libraries inject their stylesheets after CssBaseline (React Flow's
  // arrives inside a lazily-loaded route chunk), so at equal specificity theirs
  // wins. Every selector therefore repeats its own class. That reads exactly
  // like a typo, and deleting it re-breaks dark mode in a way no other test
  // here would notice, because these functions return the same values either
  // way — what changes is only whether the browser applies them.
  it('every selector doubles its leading class', () => {
    const styles = thirdPartySurfaceStyles(createAppTheme('dark'));
    const selectors = Object.keys(styles);
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      const leading = selector.split(' ')[0];
      const cls = leading.split('.').filter(Boolean);
      expect(cls.length, `${selector} must repeat its class to out-specify the library's own rule`).toBe(2);
      expect(cls[0]).toBe(cls[1]);
    }
  });
});

describe('topology edge labels', () => {
  it.each(['light', 'dark'] as const)('%s: the label is readable on its own background', (mode) => {
    const theme = createAppTheme(mode);
    const style = edgeLabelStyle(theme);

    // The original defect was two-sided: a hardcoded white background AND no
    // colour at all, so the text inherited the theme's. Either alone is enough
    // to make the label vanish, so pin both.
    expect(style.color).toBeDefined();
    expect(style.background).toBe(theme.palette.background.paper);
    expect(contrast(String(style.color), String(style.background))).toBeGreaterThanOrEqual(4.5);
  });
});
