import type { CSSProperties } from 'react';
import { alpha, createTheme, type Theme } from '@mui/material/styles';
import type { PaletteMode } from '@mui/material';

/**
 * FullCalendar and React Flow each ship a stylesheet that hardcodes a light
 * surface, and neither knows the MUI palette exists. In dark mode their
 * surfaces therefore stayed white while the text on them inherited the theme's
 * white — the calendar's weekday headings and the topology's edge labels both
 * rendered at a contrast ratio of 1.00.
 *
 * Derive their colours from the palette instead, in ONE place, applied through
 * CssBaseline. Do not "fix" a page by overriding these on the page: a second
 * opinion on a shared surface is how the two calendars drifted apart before.
 * Values are palette-derived in both modes rather than gated on `mode === dark`
 * — a light-mode-only branch is what rots the next time the palette moves.
 *
 * EVERY SELECTOR HERE DELIBERATELY REPEATS ITS CLASS (`.x.x`). Both libraries
 * ship their stylesheets as a side effect of importing them, which for
 * React Flow happens inside a lazily-loaded route chunk — i.e. AFTER
 * CssBaseline has injected. At equal specificity the later rule wins, so a
 * single-class selector loses. It loses SILENTLY AND ONLY IN PART, which is
 * worse than losing outright: `fill` (which React Flow sets as a longhand)
 * applied while `background` (which it sets as a shorthand) did not, turning
 * the zoom controls into white glyphs on a white button. The repeated class
 * doubles specificity without `!important`. Removing it as a typo re-breaks
 * this; `darkModeSurfaces.test.ts` pins it.
 */
export function thirdPartySurfaceStyles(theme: Theme) {
  return {
    // FullCalendar v6 exposes its surfaces as CSS variables; setting them is
    // the supported way to theme it. --fc-page-bg-color is the one that
    // matters most: it paints the sticky header row the day names sit on.
    '.fc.fc': {
      '--fc-page-bg-color': theme.palette.background.paper,
      '--fc-border-color': theme.palette.divider,
      '--fc-neutral-bg-color': theme.palette.action.hover,
      '--fc-neutral-text-color': theme.palette.text.secondary,
      '--fc-list-event-hover-bg-color': theme.palette.action.hover,
    },
    // React Flow's chrome (minimap, zoom controls, attribution) exposes no
    // theming hooks, so these are class overrides against its own stylesheet.
    '.react-flow__minimap.react-flow__minimap': {
      backgroundColor: theme.palette.background.paper,
    },
    '.react-flow__minimap-mask.react-flow__minimap-mask': {
      fill: alpha(theme.palette.background.default, 0.6),
    },
    '.react-flow__minimap-node.react-flow__minimap-node': {
      fill: theme.palette.action.disabled,
    },
    '.react-flow__controls-button.react-flow__controls-button': {
      backgroundColor: theme.palette.background.paper,
      borderBottom: `1px solid ${theme.palette.divider}`,
      color: theme.palette.text.primary,
      '&:hover': { backgroundColor: theme.palette.action.hover },
      // React Flow's own rule fills the glyph #000; follow the button instead.
      '& svg': { fill: 'currentColor' },
    },
    '.react-flow__attribution.react-flow__attribution': {
      backgroundColor: 'transparent',
    },
    '.react-flow__attribution.react-flow__attribution a': {
      color: theme.palette.text.secondary,
    },
  };
}

/**
 * The plate a topology edge's dependency type sits on.
 *
 * Lives here rather than in FloatingEdge.tsx for the same reason as the block
 * above: one place decides how a third-party surface follows the palette. It
 * needs a solid background so the edge line does not run through the text, and
 * therefore it MUST set its own colour too — it used to paint a hardcoded white
 * plate (behind a `var(--mui-palette-background-paper)` that never resolved,
 * since this app does not enable MUI's CSS variables) and let the text inherit,
 * which in dark mode was white on white.
 */
export function edgeLabelStyle(theme: Theme): CSSProperties {
  return {
    background: theme.palette.background.paper,
    color: theme.palette.text.primary,
  };
}

export function createAppTheme(mode: PaletteMode): Theme {
  const isLight = mode === 'light';
  const base = createTheme({
    palette: {
      mode,
      primary: {
        main: '#1976d2',
      },
      secondary: {
        main: '#dc004e',
      },
      // Subtle page background so outlined cards/tables read as surfaces (light mode only).
      ...(isLight
        ? { background: { default: '#f5f6f8', paper: '#ffffff' } }
        : {}),
    },
    shape: {
      borderRadius: 8,
    },
    typography: {
      fontFamily: [
        '-apple-system',
        'BlinkMacSystemFont',
        '"Segoe UI"',
        'Roboto',
        '"Helvetica Neue"',
        'Arial',
        'sans-serif',
      ].join(','),
      // A real heading scale so page/section hierarchy is consistent app-wide.
      h4: { fontSize: '1.6rem', fontWeight: 600 },
      h5: { fontSize: '1.3rem', fontWeight: 600 },
      h6: { fontSize: '1.05rem', fontWeight: 600 },
      subtitle1: { fontWeight: 600 },
      subtitle2: { fontWeight: 600 },
      // Modern: sentence-case buttons instead of ALL CAPS.
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiButton: {
        defaultProps: {
          disableElevation: true,
        },
      },
      MuiChip: {
        styleOverrides: {
          root: { fontWeight: 600 },
        },
      },
      MuiDialogContent: {
        styleOverrides: {
          root: {
            // overflow: auto clips the absolutely-positioned floating label on the first field
            overflowY: 'visible',
            // Restore scrolling on the Paper instead (handled by Dialog's scroll="paper" default)
          },
        },
      },
      MuiDialog: {
        defaultProps: {
          PaperProps: {
            sx: { overflowY: 'auto' },
          },
        },
      },
    },
  });

  // Second pass: the third-party surface rules need the RESOLVED palette
  // (background.paper, divider, …), which only exists once the base theme is
  // built. CssBaseline is already rendered once, in ThemedApp.
  return createTheme(base, {
    components: {
      MuiCssBaseline: {
        styleOverrides: thirdPartySurfaceStyles(base),
      },
    },
  });
}

// Back-compat export: fallback static light theme for any callers still importing `theme`.
export const theme = createAppTheme('light');
