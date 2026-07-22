import { createTheme, type Theme } from '@mui/material/styles';
import type { PaletteMode } from '@mui/material';

export function createAppTheme(mode: PaletteMode): Theme {
  const isLight = mode === 'light';
  return createTheme({
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
}

// Back-compat export: fallback static light theme for any callers still importing `theme`.
export const theme = createAppTheme('light');
